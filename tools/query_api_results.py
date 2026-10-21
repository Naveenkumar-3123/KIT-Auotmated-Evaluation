import sqlite3
import json

def check():
    con_jobs = sqlite3.connect('data/jobs.db')
    cur_jobs = con_jobs.cursor()
    
    rows = cur_jobs.execute("SELECT submission_id, payload FROM results").fetchall()
    
    for sub_id, payload_str in rows:
        data = json.loads(payload_str)
        t_awarded = data.get('total_marks_awarded')
        t_max = data.get('total_possible_marks')
        qs = data.get('questions', [])

        # If questions is a dict (qid -> details)
        if isinstance(qs, dict):
            qs_list = []
            for qid, qval in qs.items():
                if isinstance(qval, dict):
                    qval['question_id'] = qid
                    qs_list.append(qval)
            qs = qs_list

        # If t_awarded is None, calculate from questions if available
        if (t_awarded is None or t_max is None) and qs:
            calc_awarded = 0.0
            calc_max = 0.0
            has_scores = False
            for q in qs:
                if isinstance(q, dict):
                    sc = q.get('final_score') if q.get('final_score') is not None else q.get('score')
                    mx = q.get('maximum_marks') if q.get('maximum_marks') is not None else q.get('max_marks')
                    if sc is not None and mx is not None:
                        calc_awarded += float(sc)
                        calc_max += float(mx)
                        has_scores = True
            if has_scores:
                t_awarded = calc_awarded
                t_max = calc_max

        t_awarded = float(t_awarded or 0.0)
        t_max = float(t_max or 0.0)
        pct = (t_awarded / t_max * 100) if t_max > 0 else 0.0
        
        print("\n" + "=" * 70)
        print(f"SUBMISSION ID: {sub_id}")
        print(f"TOTAL MARKS GAINED: {t_awarded:.1f} / {t_max:.1f} ({pct:.1f}%)")
        print(f"Questions Count: {len(qs)}")
        print(f"Auto-Approved: {data.get('auto_approved_count', 'N/A')} | Flagged for Review: {data.get('flagged_for_review_count', 'N/A')}")
        print("=" * 70)
        
        for q in qs:
            if isinstance(q, str):
                print(f"  * Question: {q}")
            elif isinstance(q, dict):
                qid = q.get('question_id', 'Q?')
                sc = q.get('final_score') if q.get('final_score') is not None else q.get('score')
                mx = q.get('maximum_marks') if q.get('maximum_marks') is not None else q.get('max_marks')
                auto = q.get('auto_approved') if q.get('auto_approved') is not None else q.get('auto_approve')
                risk = q.get('risk_level', 'N/A')
                fb = (q.get('feedback') or '').strip().replace('\n', ' ')
                sc_str = f"{float(sc):4.1f}" if sc is not None else " N/A"
                mx_str = f"{float(mx):4.1f}" if mx is not None else " N/A"
                print(f"  * {str(qid):4s}: {sc_str} / {mx_str} marks | Auto-Approve: {str(auto):5s} | Risk: {str(risk):6s}")
                if fb:
                    print(f"        Feedback: {fb[:100]}...")
                for c in q.get('criteria', []):
                    if isinstance(c, dict):
                        cid = c.get('criterion_id', 'C?')
                        stat = c.get('status', '')
                        pm = c.get('proposed_marks', 0)
                        mm = c.get('maximum_marks', 0)
                        rsn = (c.get('reason') or '').strip().replace('\n', ' ')
                        print(f"          [{cid}] ({stat}): {pm}/{mm} -> {rsn[:75]}...")

    con_jobs.close()

if __name__ == '__main__':
    check()

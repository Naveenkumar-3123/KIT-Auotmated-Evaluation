import sqlite3
import json
import sys

def inspect_results():
    con = sqlite3.connect('data/jobs.db')
    cur = con.cursor()
    
    print("=" * 70)
    print("API PAPER EVALUATION: MARKS GAINED REPORT")
    print("=" * 70)
    
    rows = cur.execute('SELECT submission_id, payload FROM results').fetchall()
    if not rows:
        print("No results found in results table.")
    
    for sub_id, payload_str in rows:
        data = json.loads(payload_str)
        print(f"\n=======================================================")
        print(f"SUBMISSION ID: {sub_id}")
        print(f"=======================================================")
        total_awarded = data.get('total_marks_awarded')
        if total_awarded is None:
            total_awarded = data.get('total_score')
        if total_awarded is None:
            total_awarded = data.get('awarded_marks')

        total_max = data.get('total_possible_marks')
        if total_max is None:
            total_max = data.get('maximum_marks')
        if total_max is None:
            total_max = data.get('total_marks')
        
        # Check questions format
        qs = data.get('questions', [])
        if isinstance(qs, dict):
            qs_items = []
            for qid, qdata in qs.items():
                if isinstance(qdata, dict):
                    qdata['question_id'] = qid
                    qs_items.append(qdata)
                else:
                    qs_items.append({"question_id": qid, "data": qdata})
            qs = qs_items

        if total_awarded is None and qs:
            total_awarded = sum(float(q.get('final_score') if q.get('final_score') is not None else q.get('score', 0.0)) for q in qs if isinstance(q, dict))
            total_max = sum(float(q.get('maximum_marks') if q.get('maximum_marks') is not None else q.get('max_marks', 0.0)) for q in qs if isinstance(q, dict))

        pct = (total_awarded / total_max * 100) if total_max else 0.0
        print(f"TOTAL MARKS GAINED: {total_awarded:.1f} / {total_max:.1f} ({pct:.1f}%)")
        print(f"Questions Evaluated: {len(qs)}")
        print(f"Auto Approved: {data.get('auto_approved_count')} | Flagged for Review: {data.get('flagged_for_review_count')}")
        print(f"Overall Risk Level: {data.get('overall_risk_level')}")
        print("\n--- Question-by-Question Marks Breakdown ---")
        for q in qs:
            if not isinstance(q, dict):
                print(f"  {q}")
                continue
            qid = q.get('question_id')
            score = q.get('final_score') if q.get('final_score') is not None else q.get('score')
            max_m = q.get('maximum_marks') if q.get('maximum_marks') is not None else q.get('max_marks')
            auto = q.get('auto_approved') if q.get('auto_approved') is not None else q.get('auto_approve')
            risk = q.get('risk_level')
            fb = (q.get('feedback') or '')[:110].replace('\n', ' ')
            score_str = f"{float(score):4.1f}" if score is not None else " N/A"
            max_str = f"{float(max_m):4.1f}" if max_m is not None else " N/A"
            print(f"  {str(qid):4s}: {score_str} / {max_str} marks | Auto-Approve: {str(auto):5s} | Risk: {str(risk):6s}")
            if fb:
                print(f"        Feedback: {fb}")
            for c in q.get('criteria', []):
                if isinstance(c, dict):
                    cid = c.get('criterion_id')
                    stat = c.get('status')
                    p_m = c.get('proposed_marks')
                    m_m = c.get('maximum_marks')
                    rsn = (c.get('reason') or '')[:80].replace('\n', ' ')
                    print(f"          [{cid}] ({stat}): {p_m}/{m_m} -> {rsn}")

    con.close()

if __name__ == "__main__":
    inspect_results()

# Validation Notes

## Visual Review

The desktop landing page presents the intended soft premium workspace: a compact left rail, restrained top header, left-aligned product story, assistant companion, stepped feature cards, product preview, and clear final conversion path. The comparison workspace retains the same visual system while prioritizing large document editors, clear empty metrics, settings, difference evidence, and detailed analysis.

The responsive mobile pass confirms that the header condenses to a menu trigger, landing hero and assistant stack without crowding, feature and workflow cards collapse into a readable single column, and the comparison workspace stacks metric cards and editors in the requested operational order.

## Functional Checks

The project passes TypeScript checking and the production build. The client-side comparison module supports strict and selected normalized comparison rules, calculates character and word metrics, produces edit-operation evidence, allows text-file loading, copy actions, reset, and a loadable example. A future backend can replace the comparison module while retaining the presentation contracts.

## Reference-Led Revision Validation

The revised desktop landing page now follows the uploaded page’s structural rhythm more directly: a full lavender backdrop frames one inset frosted panel; a narrow circular icon rail replaces the expanded dashboard sidebar; the small utility header, large empty hero field, mascot-and-speech-bubble cluster, three overlapping feature cards, and bottom action dock all remain visible in the initial viewport. OCR-specific copy and document actions replace every chat affordance.

The workspace inherits the same panel, lighting, capsule controls, and soft-card materials while adding a document intake surface ahead of the existing ground-truth and OCR comparison flow. On mobile, the rail collapses into the menu trigger and the hero, assistant, cards, action dock, intake, metrics, editors, and evidence sections stack into a readable single-column flow.

## Production Polish Pass

The latest desktop review confirmed that the central panel now exposes the entire landing and comparison experiences through normal document flow rather than a nested, height-constrained scroll region. The compact tool rail and top header stay available without clipping page sections. A mobile check identified the assistant entering the supporting-copy zone in the hero; the landing hero now reserves a dedicated lower visual area on narrow screens so the mascot remains integrated without covering the headline, supporting copy, or actions.

The final mobile review confirmed that the headline, body copy, primary workspace action, assistant, feature cards, action dock, and lower content now appear in a single stable scroll sequence. The secondary hero action is desktop-only, preventing a narrow-screen collision with the assistant speech bubble while maintaining the intended visual hierarchy.

## Typography and OCR Identity Pass

The previous type system depended on closely packed heavy weights, ad hoc pixel sizes, and a display line break that made the landing hero feel generic. The new system uses Geist for interface copy and JetBrains Mono only for measured OCR text and values. It defines reusable overline, display, page-title, section-title, card-title, body, support, metadata, button, and metric scales. Desktop review confirmed improved line wrapping in the hero, clearer CTA hierarchy, more readable cards, and consistent workspace labels.

The visual pass also established a more explicit OCR identity without changing the overall composition: the optical-focus mark is now visible in primary navigation states, controlled periwinkle scan rules frame card and metric evidence, and focus-corner marks anchor the scanning companion. Copy was adjusted from generic productivity language toward concrete review, verification, and evidence actions.

The mobile review confirmed that the revised hero display has an intentional two-line wrap, practical body text width, readable 13px-scale primary action, and clear separation between product copy and the assistant. The benefit list is retained for wider screens, where it supports the hero’s horizontal composition, and is removed on mobile so the scanning companion keeps a dedicated visual zone. Workspace labels, buttons, editor metadata, and metric cards remain legible in the narrow single-column flow.

## Direct Visual Edit Verification

The landing feature cards no longer use a negative top margin or staggered vertical translation, so they begin below the hero with a consistent gap rather than covering its lower area. The action dock is no longer mounted on the home page. The former navigation icon stack has been replaced with a minimally framed, translucent glass rail containing the OCR Eval mark and a small system-status cue; the home and workspace pages retain stable framing without dashboard controls along the rail.

## Staggered Card Cluster Refinement

The capability area now follows the user-provided card reference: three clean white cards form an offset composition with the center card raised, while a smaller OCR scanning companion and guide callout anchor the upper-right card area. The cluster remains distinctly below the hero banner, and the companion is deliberately lowered to overlap the top edge of the rightmost card rather than floating in unused space.

## Dashboard Restoration Verification

The restored rail now exposes Home, Workspace, Documents, History, Accuracy, and Settings controls at desktop width, with a clear active state for the current section. The dashboard frame, rail, and header use low-opacity white glass with reduced border contrast, allowing the cool lavender studio background to remain visible through the shell while the content panels preserve their stronger white surfaces for readability. Landing and workspace captures confirm that the navigation and comparison workspace remain visible and usable.

## Feature Card Typography Edit

The feature-card container now loads and uses Inter. The requested 16px, 500-weight, 1.18 line-height, and -0.2px letter-spacing treatment is applied to the card content and reinforced explicitly on each card title and description. The landing review confirms stronger text presence and more even card hierarchy while retaining the compact all-caps category labels as secondary metadata.

## Full-Width Card Cluster Verification

The card cluster now extends across the full available landing canvas rather than being constrained to a narrow 820px group. Desktop review confirms three substantially wider cards with an evenly distributed left, center, and right composition; the companion shifts with the expanded right-side card. On mobile, the wider rules resolve to a clean full-width single-column stack, and the companion remains positioned above the first card without obscuring its title or description.

## EvalAI Assessment Platform Rebrand

The visible product identity now communicates automatic question-paper evaluation rather than OCR testing. The header, rail, browser metadata, hero, assistant speech/status, workflow steps, feature cards, supporting content, and workspace labels consistently use EvalAI, assessment, marking scheme, answer evaluation, teacher review, and results language. The secondary card-cluster mascot was removed so the single hero assistant remains the friendly grading guide.

The evaluation workspace now presents assessment input, expected answer and student answer panels, teacher-facing review notes, and non-fabricated production metrics that remain pending until a grading service is connected. Desktop and mobile review confirm the approved glass composition remains intact and the new academic copy is readable throughout the primary views.

## Centered Hero Assistant

The desktop hero assistant now uses a fixed left-positioned visual zone at the center of the hero’s right-side space rather than being anchored to the far right edge. Its guide bubble and evaluation-status callout remain anchored to the assistant frame, keeping the copy area clear and the single-character composition balanced. Narrow-screen placement is unchanged so the assistant retains its dedicated mobile zone.

## Configure Page Validation

The new `/configure` route is reachable from the second sidebar item, which maintains an active configuration state while preserving the existing dashboard shell. Desktop review confirms the page uses the same glass cards, lavender studio background, premium header treatment, compact step progress, and one visual guide assistant beside the active setup area.

The mobile view keeps the required reading order: setup header, progress indicator, active upload or form surface, then the assistant guidance panel. All staged actions remain frontend-only. ZIP and answer-key selection simulate progress and completion, class and subject selectors activate strictness controls, both range and individual strictness modes are represented in local state, and save stores only local browser state.

## Global Inter and Configure Fit Refinement

Inter is now the global UI typeface across EvalAI, with JetBrains Mono retained only for measured technical-style values. The shared display, page, section, body, support, and button scales were increased so the interface reads more clearly at the dashboard’s desktop size.

The active Configure stage now has a desktop minimum height derived from the available viewport and the upload surface grows within that stage. This replaces the visible lower blank area with a proportionally larger setup workspace and guide panel. Desktop and mobile reviews confirm the larger typography remains readable and the mobile flow retains natural scrolling rather than forcing a fixed-height panel.

## Teacher-Managed Classes and Subjects

Assessment Details now receives its selectable class and subject lists from Configure-page state rather than immutable component constants. Each selector includes an accessible **Add class** or **Add subject** action that opens a compact inline entry field. Entered values are added only to frontend state, selected immediately, and announced through a toast; no directory, database, or backend claim is introduced. The Configure route still renders successfully and TypeScript plus the production build pass.

## EvalBot Guide Replacement

The uploaded EvalBot asset is now stored as a managed project asset and replaces the former scanner-orb mascot in both the landing hero and Configure guidance panel. On desktop, the full illustrated character remains within the existing guide frame with the speech and status callouts intact. On mobile, the hero and Configure card retain a stacked, readable composition; the assistant occupies its own visual area below the primary content rather than covering text or controls.

## Transparent Centered EvalBot

The guide image was processed into a background-cleared asset and the hero and Configure guide layers now use a centered, tightly cropped character treatment. A visual blend layer clears the original light studio backdrop against the existing white-and-lavender product canvas, while the cropped guide frames suppress peripheral illustration detail. Desktop capture confirms the character now reads as a centered standalone assistant rather than a white image card; the guide and status callouts remain legible.

## Exact Hero Guide Centering

EvalBot is now anchored at the 50% vertical center of the right-side hero guide area and at the 75% horizontal visual anchor, which is the midpoint of that reserved right-side space. The speech bubble and evaluation status card remain positioned relative to this same frame. On mobile, the hero reserves additional lower space for the centered assistant, keeping the primary evaluation action visibly separated above the guide composition.

## Configure Guide Centering

The Configure guide panel now uses a larger lower visual zone with EvalBot anchored at the horizontal center. The guidance card remains above the character, leaving a clear text area, while the bot’s larger scale is fully visible through its expanded desktop and mobile guide frame. Desktop and mobile captures confirm the character’s body, clipboard, and feet remain inside the panel without overlaying the teacher instructions.

## Prominent Configure EvalBot

The desktop Configure guide now gives EvalBot a substantially larger 340px visual frame, centered horizontally and vertically in the lower guide region beneath the instructions. The panel retains a readable instruction card at the top while the enlarged character is fully visible from antenna to feet. The mobile-specific guide layout is preserved, retaining its centered, full-character treatment without forcing the teacher instructions to compete with the illustration.

## Evaluation Workspace Validation

The new `/evaluation` route is integrated into the active dashboard navigation and header. The initial class-selection state presents configured assessments through review-oriented cards, including verified answer-sheet counts, focus-corner geometry, scan-line evidence rules, and a task-specific EvalBot guide. Desktop review confirms the guide is visible in the header cluster, card offsets preserve a composed hierarchy, and the Evaluation rail state is active. The mobile layout turns the same elements into a readable single-column sequence without horizontal overflow.

The Evaluation page uses centralized frontend-only state to support the required flow: choosing a class, reviewing sheets and assessment configuration, opening honest preview placeholders, adding a mock missing PDF entry, confirming simulated evaluation, watching auto-advancing worker/pipeline/queue states, reaching completion, and continuing to a transparent results placeholder. No OCR, file parsing, network calls, worker registration, or grading claims are implemented.

### Compact EvalBot Guide Correction

The compact Evaluation guide was recomposed into a distinct left-message and right-mascot arrangement. EvalBot now uses a dedicated, top-aligned 160px visual frame outside the message card instead of being positioned beneath it. Desktop validation confirms the full character, including its face and lower body, is visible beside the contextual instruction while the glass guide remains compact and readable.

### Wider Horizontal Evaluation Guide

The desktop Evaluation guide now uses a 368px horizontal card with an independently bounded guidance panel on the left and a dedicated 174px EvalBot treatment on the right. This expands the content safely without allowing the mascot to cover the instruction. The class-selection header reserves a shorter text column to maintain a clean visual gap before the enlarged guide. Desktop capture confirms the full message and character fit without clipping; mobile retains its uncluttered, stacked class-selection layout with the desktop-only guide intentionally omitted.

### Evaluation Card Line Alignment

The configured-class cards no longer inherit the focus-corner or scan-baseline decorations that previously intersected their content. Their visual hierarchy now comes from the softly tinted student icon, verified-status check, clear title-and-subject block, and positioned Review action. Desktop validation at the supplied compact desktop width and mobile validation confirm that card content is clear and unclipped while the larger Evaluation header retains its separate evidence framing.

### Equal Configured-Class Card Alignment

Configured-class cards now use a fixed 210px height and have no responsive vertical offsets. This gives the complete desktop class row a consistent top and bottom edge, independent of each class’s label length, while retaining the shared hover behavior and footer action alignment. Desktop and mobile captures confirm the cards remain evenly composed in both the four-column and single-column layouts.

## Results Workspace Validation

The new `/results` workspace is integrated into the dashboard rail directly after Evaluation and uses the existing Results active state. The first view presents completed or partially complete assessments; choosing one opens `/results/:classId` with a measured summary, search, lightweight status filter, sort control, responsive roster, and a non-functional export-preparation action. Evaluation completion already links directly to its class result route.

The student route `/results/:classId/:studentId` presents total score, question count, review status, twenty question-level results, strictness badges, concise evaluation explanations, and a teacher-mark override draft interface that deliberately does not persist changes. A question opens a detailed side drawer with the question, response, expected key points, evaluation explanation, and score. Answer-sheet preview, Original, Preprocessed, Segments, OCR, and Evaluation Data appear only as clearly labeled frontend-only placeholders under secondary technical evidence controls.

Desktop captures cover assessment selection, the CSE-II roster, and the 24CSE001 question review. Mobile captures confirm the class cards, summary surfaces, roster controls, and student score header resolve into a readable vertical flow. The review refinement adds document-edge evidence rails, periwinkle observation details, and JetBrains Mono for measured scores and roster identifiers. Type checking and the production build pass; the sole build message is the existing non-blocking large-bundle warning.

## Sidebar Visual Edit Validation

The visual editor’s selector pointed to the shared mapped navigation button and could not identify a single control. After clarification, Settings, Answer Sheets, and Review were removed from the rail along with their unused icon imports and obsolete coming-soon branching. The Sidebar now presents only active, teacher-relevant navigation: Home, Configure, Evaluation, and Results. Type checking passes, and the desktop Results capture confirms the lower inactive icon stack has been removed without affecting the active Results state.

## Configure Word-Count Flow Checkpoint

Browser validation progressed through the frontend-only answer-paper upload, answer-key upload, and assessment-detail selections to open Step 4. The configured screen presents strictness and full-mark word-count as two distinct, teacher-readable rule groups. Both use Question ranges and Individual questions modes. The range word-count mode exposes From question, To question, Minimum words, and Add count controls, with a default eligible minimum of 100 words.

The browser flow added both Q1–Q5 strictness and Q1–Q5 minimum-word-count rules, then confirmed that the readiness gate enables only after both policy categories have a rule. The Configuration Review screen displays the selected Question ranges mode, the explanatory “Minimum response length eligible for full marks” label, and the final `Q1–Q5 · 100 words` entry. A mobile screenshot confirms the Configure shell continues to stack correctly; type checking and the production build pass after the addition.

## Five-Step Configure Flow Checkpoint

The updated browser flow shows five progress labels: Answer papers, Answer key, Assessment details, Evaluation rules, and Global policy. After reaching Step 4, both the strictness and word-count rule modes remain available, and the fifth Global policy indicator stays inactive until both rule groups are complete.

Browser validation then added the Q1–Q5 strictness range and Q1–Q5 minimum-word-count range. The Step 4 readiness message changed to confirm both rule categories are ready for review, and the fifth Global policy progress control became eligible to open.

The fifth step renders **Word-count deduction policy** with an explicit assessment-wide scope notice. It provides separate inputs for the shortfall threshold and mark deduction, defaulting to 20 words below the configured minimum and a 1-mark deduction. The example updates from those values and notes that strictness and the marking scheme remain part of the evaluation. The final review screen confirms `20 words below minimum` and `Deduct 1 marks across this assessment` as the global policy.

The review summary grammar was refined to use singular or plural mark labels correctly. Final type checking and production build validation passed after the five-step policy update; the only build message remains the existing non-blocking large-bundle warning.

## Login and Sign Up Validation

Standalone `/login` and `/signup` routes sit outside the authenticated dashboard shell and retain a direct Home route. Both forms have labels, email/password browser semantics, password visibility controls, keyboard focus styling, required-field validation, and a transparent frontend-only success notification before taking the teacher to the Evaluation workspace. The Sign Up route additionally requires a teacher-use acknowledgment.

Desktop captures verify the asymmetrical glass composition, full EvalBot companion context, periwinkle principal action, source-evidence scan rule, focus corners, capture-status tile, and optical-focus brand treatment. Mobile captures verify that the public screens become a clean single-column form without clipping or horizontal overflow. Type checking and production builds pass after the visual refinement; the only build message remains the non-blocking large-bundle warning.

## Teacher Profile Flow Checkpoint

Browser validation confirms that visiting the protected `/configure` route without a session redirects to `/login`. The expanded Sign Up route displays required personal fields plus searchable, chip-based department and subject multi-selects. Selecting Computer Science & Engineering limits the subject picker to CSE-related subjects—including Machine Learning, Artificial Intelligence, Deep Learning, Natural Language Processing, Data Structures, Operating Systems, Database Management Systems, and Computer Networks—rather than exposing unrelated department subjects.

The local browser demo then created a Dr. Ananya Rao teaching profile with a remembered session and a selected CSE subject. The app redirected to Home, showed an initials-based teacher control in the header, and allowed access to the protected Configure workflow. This verifies that the profile and session store persist through public-to-workspace navigation without storing a password.

The protected Settings route renders a dedicated Teaching Profile view with teacher identity, selected departments, and selected subjects. Browser validation opened Edit Profile, exposed the same searchable subject picker scoped to CSE, and added Machine Learning alongside the previously selected Deep Learning before the local save action. This confirms that profile editing uses the centralized frontend-only state rather than assessment-local options.

After saving the profile, the Configure flow was reopened and advanced through its mock uploads. The CSE assessment details subject field immediately updated from only Deep Learning to Machine Learning and Deep Learning, confirming that saved profile selections propagate to Configure without re-entering subjects. Final desktop and mobile captures confirm Login and Sign Up retain clear, responsive field hierarchy; the desktop teacher account screen also now shows the prominent source-sheet signal, measured evidence lines, document-edge frame, and scanning-companion composition.

The header’s initials-based teacher control opens a compact menu containing Teaching Profile, Settings, and Sign Out. Browser validation confirmed Sign Out clears only the active frontend session and returns to Login while retaining the non-sensitive local profile. Logging back in with the profile email and a valid placeholder password restored the personalized workspace and surfaced a transparent frontend-only success message.

## Comma-Separated Subject Entry Validation

Subjects You Teach is now teacher-authored rather than selected from a catalog. The Sign Up screen explicitly instructs teachers to separate multiple subjects with commas, provides the example `Machine Learning, Artificial Intelligence, Deep Learning`, counts parsed subjects, and renders each parsed name as a lightweight confirmation chip. Browser validation entered that exact comma-separated string and confirmed all three independent subject chips appeared. Teaching Profile editing uses the same field; the centralized profile store sends the resulting names directly to Configure as the teacher’s personalized subject options.

### Teacher Profile Menu Cleanup

The authenticated header profile menu now contains only the teacher identity, Teaching Profile, and Sign Out. The redundant Settings row was removed while Teaching Profile continues to route to the existing `/settings` teaching-profile page. Type checking and the production build pass after the cleanup, and browser validation confirms the simplified two-action dropdown.

## Processing Computers Workspace Validation

The protected `/computers` route is integrated into the primary rail as **Computers** and shows the active state. The teacher-facing dashboard leads with four computers connected and a healthy network indicator, then presents connected, processing, idle, and offline metrics, a capacity indicator showing three of four computers busy, search and status filters, and four frontend-only worker cards. The active cards report only teacher-relevant data: student roll number, class, subject, current evaluation stage, and progress. The idle card explicitly explains that it remains online and ready for the next answer sheet.

Browser validation opened Computer 01 and confirmed its side drawer contains connection and processing status, current student, class, subject, human-friendly stage, progress, last activity, and collapsed technical details. The drawer marks all figures as frontend demonstration data; no device discovery, networking, workers, or real-time service is implemented. Type checking and the production build pass; the existing only build advisory remains the non-blocking bundle-size warning.

## Global Diagram Policy Validation

The fifth Configure step now contains a global Diagram requirement section alongside the existing word-count deduction policy. Teachers can choose **Diagrams are required** or **No diagram requirement**. When required, the screen asks for the minimum diagram count and supplies a single missing-diagram deduction when the count is one; selecting multiple diagrams creates a distinct deduction field for Diagram 1, Diagram 2, and each later diagram. The count is bounded to six so the policy remains readable.

The policy prominently notes that diagram order is collected from the answer key, and the final configuration review summarizes the chosen requirement plus individual deductions. Browser validation completed the mock upload, class, subject, strictness, and word-count prerequisites; it then opened the fifth step, verified the no-diagram and required-diagram states, the answer-key order notice, one-diagram rule, and multiple per-diagram controls. Type checking and production build pass; no diagram analysis, answer-key parsing, or mark deduction is executed in this frontend prototype.

### Half-Mark Deduction Support

Global word-count deductions and every missing-diagram deduction now accept a minimum of **0.5 marks** in 0.5-mark increments. The helper text on each relevant field makes this explicit. Required diagram counts remain whole numbers, with a practical upper limit of six so the per-diagram policy remains readable. The configuration-review grammar already handles singular and plural marks correctly, including half-mark values. Type checking and production build pass after this refinement.

## Analytics Workspace Validation

The new protected `/analytics` route appears as the fifth primary Sidebar item, immediately before Computers, and has the expected active-state treatment. The class dashboard presents the requested academic-performance hierarchy: class and subject controls, measured pass/fail, average, high, and low summary cards, a calm pass/fail donut, score-distribution bars, question-performance bars, concept-difficulty bars, class observations, teaching focus, and a roll-number-first student table.

Browser validation confirms the authenticated Analytics route opens with all expected mock assessment content, and `/analytics/24CSE001` opens the dedicated student dashboard. The student view contains score, percentage, class rank, status, question-performance bars and mark rows, strong concepts, needs-improvement concepts, a performance insight, and a recommended revision. Search and sort are frontend-local controls over the mock roster. All statistics, ranks, insights, and charts are static interface sample data only; no calculations, recommendation engine, OCR metrics, or backend services are used. Type checking and production build pass; the only build advisory remains the pre-existing non-blocking bundle-size warning.

The authenticated dashboard rail shows Analytics immediately before Computers, and the header context changes to Performance Analytics. Direct navigation to the class and student routes confirms the protected route and master/detail layout resolve correctly in the live frontend session.

Browser interaction also changed the local roster Sort By control to Rank and confirmed the mock student list reordered from rank #1 through #22, without any network call or persistence.

## Analytics Difficulty and Content Refinement

The class and student Analytics routes now present **Question Difficulty** as a colour-coded pie chart. Green marks easier questions, periwinkle marks moderate performance, and rose marks difficult questions; the adjacent question score records preserve the exact mock percentages in a compact, accessible text format. Browser validation confirmed the class route shows Q1–Q5 with the intended colour legend and that `/analytics/24CSE001` renders the matching student-specific pie chart and question record.

AI-style observations, teaching-focus suggestions, individual performance insights, revision recommendations, and semantic strength/improvement panels were removed. The remaining surfaces show only transparent frontend-only mock academic results: summary values, pass/fail, score distribution, question difficulty, score records, and the searchable/sortable student roster. Type checking and the production build pass; the existing bundle-size advisory remains non-blocking.

## Compact Student Analytics Overlay

The student **View Analytics** action now opens a compact, centered overlay above the active class dashboard rather than navigating to a separate route. The blurred class dashboard remains visible beneath the overlay, preserving the class, subject, charts, roster, search state, and scroll context. The overlay contains the selected student’s mock score, percentage, rank, status, colour-coded question-difficulty pie chart, and factual question-score record only.

Browser validation opened the first roster record, confirmed that the address remains `/analytics`, and confirmed that the overlay has an accessible close button. Closing it returned directly to the unchanged class dashboard without route navigation. The responsive overlay uses a viewport-safe height, two-column mobile metrics, and a single-column chart-to-score-record layout before widening on desktop. Type checking and the production build pass; only the existing non-blocking bundle-size advisory remains.

## View Analytics Viewport Refinement

The compact student overlay now uses more deliberate desktop and mobile proportions. On desktop, it expands to a balanced 840px maximum width with a calmer header, four compact metrics, and an aligned two-column analytics-and-score-record area. The class dashboard remains softly blurred in the background to retain the teacher’s current context.

On mobile, the overlay begins with tight safe-area padding, uses a viewport-safe maximum height with internal scrolling, keeps metrics in a compact two-column rhythm, reduces the difficulty pie and legend without losing its colour meaning, and preserves a single-column reading order before widening at the desktop breakpoint. Type checking and production build validation pass; the only advisory remains the pre-existing non-blocking bundle-size warning.

## Question-Specific Diagram Rules

Configure Step 4 now includes an optional **Question diagram rules** section that mirrors the existing question-range and individual-question patterns. In range mode, teachers choose a question interval, the minimum expected diagrams, and a missing-diagram deduction for each answer-key-ordered diagram. In individual mode, each of ten questions can be marked **No diagram** or **Required**; required questions reveal the same diagram count and 0.5-mark deduction controls. Diagram counts remain whole numbers and are limited to six.

Browser validation completed the frontend-only mock upload and assessment-detail flow, opened both question-range and individual diagram modes, selected a required diagram for Question 1, and confirmed that its count and deduction inputs appeared. The final review listed `Question diagram rules: Individual questions` and the Q1 requirement with deduction detail. Type checking and production build pass; these rules remain local sample configuration only and do not analyse diagrams or apply deductions.

## Global Diagram Policy Removal

The visual-editor target was stale: it resolved to the shared `PolicyCard` wrapper rather than a unique section. To apply the intended cleanup without affecting the word-count policy, the redundant **global Diagram requirement** card was removed manually from Step 5. The global diagram state, local persistence entry, and final-review tile were also removed; question-specific diagram requirements remain available in Step 4.

Browser validation advanced through the frontend-only Configure flow to Step 5 and confirmed the page contains only the global word-count deduction policy, its explanation, and the review action. The helper text directs teachers to Step 4 for question-specific diagram requirements. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Text-Labelled Glass Dashboard Sidebar

The former narrow icon-only rail is now a taller, text-labelled glass sidebar aligned to the supplied layout direction. It keeps the translucent lavender-white material, but adds a clear EvalAI identity block, a Workspace introduction, dashboard-style text rows with supporting descriptions, active-page emphasis, and a small engine-ready status panel. The content canvas remains adjacent to the sidebar inside the same frosted application shell.

Browser validation opened Dashboard Home and then selected Analytics from the redesigned sidebar. The route changed to `/analytics`, the Analytics row received the active treatment, and class dashboard content remained usable. Type checking and the production build pass; the existing bundle-size advisory remains non-blocking.

## Compact Dark Reference Sidebar

The sidebar now follows the supplied dark navigation reference: a charcoal outer rail, a compact rounded graphite navigation capsule, a white circular EvalAI mark, concise Inter-style text, circular icon holders, and a low-contrast frosted selected-row treatment. The supplied reference’s lower verification and profile sections were deliberately omitted. A small non-interactive “Add assessment section” line preserves the reference’s lower navigation rhythm without adding an unsupported workflow.

Browser validation opened Dashboard Home and then used the compact sidebar to navigate to Configure. The route changed to `/configure`, Configure received the selected-row treatment, and the Configure workflow rendered normally. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Sidebar Scale and Full-Height Panel

The compact dark sidebar now uses larger brand and navigation labels, larger circular icon holders, taller navigation rows, and more deliberate item spacing for improved legibility. Its rounded graphite navigation surface now fills the entire available sidebar height rather than ending immediately after the final navigation item, matching the updated reference’s continuous dark-panel treatment.

Browser validation reopened Dashboard Home and confirmed that the sidebar panel now extends to the bottom of the workspace rail while retaining the compact selected Dashboard row. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Sidebar Footer Cleanup

The unused **Add assessment section** line was removed from the dark sidebar, along with its unused icon import. Browser validation confirmed that the sidebar now ends cleanly after Computers while its rounded graphite surface continues to the full height of the workspace rail. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Sidebar Font Increase

The compact dark sidebar’s EvalAI brand label increased to 15px and its navigation labels increased from 12px to 13px, preserving the existing full-height graphite panel, icon sizing, and row spacing. Browser validation confirmed the labels remain balanced and readable on Dashboard Home. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Continuous Dashboard Surface

The compact graphite dashboard surface now reaches the sidebar’s full bottom edge and the inner workspace edge on desktop, removing the secondary lower/right gutter while retaining the rounded outer shell and compact navigation composition. Browser validation on Dashboard Home confirmed the continuous dark treatment. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Unified Dashboard Shell

The dark navigation is now an integrated left column of the primary EvalAI application shell rather than an independently inset or rounded card. The outer frosted shell clips the combined layout as one unit, while the dark material fills the full column height and meets the main content at a single restrained divider. Browser validation on Dashboard Home confirmed the continuous page-level composition and usable navigation. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Persistent Dashboard Navigation

The integrated dark dashboard column now uses desktop sticky positioning with a viewport-height surface. The primary shell uses clipping that retains its unified boundaries without creating a scroll container that prevents sticky positioning. Browser validation opened the long Analytics route and scrolled into its student-performance roster; the dark sidebar remained visible and Analytics retained its active-row state. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Sidebar Menu Icon Removal

The stale visual-editor target was confirmed as the decorative desktop menu icon in the Sidebar header. It was removed manually together with its unused icon import, while the mobile close control remains intact. Browser validation on Dashboard Home confirmed that the desktop header now ends cleanly after the EvalAI identity and navigation remains usable. Type checking and production build pass; the existing bundle-size advisory remains non-blocking.

## Question-Specific Word-Count Rules

The former global word-count deduction stage was removed. Step 4 now lets teachers choose **Question ranges** or **Individual questions** for word-count policy, alongside strictness. Each rule defines a full-mark minimum word count, a shortfall trigger measured in words below that minimum, and a mark deduction in 0.5-mark increments. Configure now has four setup steps, with the review shown directly after Evaluation rules.

Browser validation completed the frontend-only mock upload and assessment-detail flow, opened range word-count controls, and confirmed the fields for minimum words, shortfall trigger, and deduction. A range rule rendered as `Q1–Q5 · 100 words · 20 below → −1 mark`. Individual mode exposed all three controls for every question, and the final review listed the same values per question. Type checking and production build pass; this remains frontend-only configuration and does not calculate live deductions.

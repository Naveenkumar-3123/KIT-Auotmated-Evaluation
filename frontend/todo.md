# Reference-Led OCR Eval Revision Checklist

- [x] Recompose the landing page into a centered, frosted workspace panel with a separate narrow icon rail.
- [x] Align the hero, mascot, floating feature cards, and bottom action module to the uploaded page’s visual rhythm while preserving OCR-focused copy.
- [x] Add polished onboarding actions for document upload, workspace access, accuracy checks, and history.
- [x] Extend the workspace with a document-processing entry point, preview area, review status, and export affordances using the same soft glass design system.
- [x] Verify the revised desktop and mobile layouts against the uploaded reference’s spacing, visual hierarchy, and restrained glass treatment.

## Production Polish Pass

- [x] Identify and correct the layout or overflow rules that cause content to vanish or become clipped while scrolling.
- [x] Establish a more deliberate typography system with refined hierarchy, line-height, and letter spacing.
- [x] Rebalance the hero, assistant callouts, card grid, rail, and bottom action dock against a consistent layout rhythm.
- [x] Improve the cool studio background and glass layers without adding distracting decorative effects.
- [x] Verify desktop, tablet, and mobile scrolling behavior and finish the visual refinement pass.

## Typography Refinement Pass

- [x] Audit current typography for oversized display text, weak hierarchy, awkward wrapping, and inconsistent microcopy.
- [x] Establish a concise product type scale and apply it to the header, hero label, hero heading, body copy, and calls to action.
- [x] Refine landing card titles, descriptions, labels, assistant callout, action-dock text, and status metadata.
- [x] Harmonize workspace headings, metrics, editor text, settings labels, controls, and helper copy with the same system.
- [x] Validate desktop and mobile type wrapping, density, and hierarchy, then complete the polish pass.

## Direct Visual Edit Requests

- [x] Remove the feature cards’ banner overlap and restore a clear visual gap below the hero.
- [x] Remove the landing-page action dock entirely.
- [x] Replace the dashboard icon stack with a minimal transparent glass sidebar rail.
- [x] Verify the simplified landing and workspace navigation, then save a checkpoint.

## Staggered Card Cluster Refinement

- [x] Rebuild the capability cards as a clean, offset three-card cluster modeled on the uploaded reference.
- [x] Add a compact scanning-companion bot and assistance callout above the card cluster.
- [x] Keep the feature cards responsive, readable, and non-overlapping on smaller screens.
- [x] Validate the updated card composition and save a checkpoint.

## Dashboard Restoration

- [x] Restore the dashboard navigation controls in the left rail.
- [x] Make the dashboard shell and rail transparent enough to show the pastel backdrop while retaining readable work surfaces.
- [x] Verify the restored dashboard on landing and workspace views, then save a checkpoint.

## Feature Card Typography Edit

- [x] Load Inter and apply the requested 16px, 500-weight, 1.18 line-height, and -0.2px tracking treatment to feature-card content.
- [x] Verify the card hierarchy and save a checkpoint.

## Full-Width Card Cluster

- [x] Expand the staggered feature-card cluster across the available dashboard canvas.
- [x] Reposition the scanning companion for the expanded composition.
- [x] Verify desktop and mobile coverage, then save a checkpoint.

## Assessment Platform Rebrand

- [x] Replace user-facing OCR Eval branding with EvalAI and assessment-focused shell language.
- [x] Rebrand the landing hero, assistant copy, workflow steps, and feature cards around question paper evaluation.
- [x] Rebrand workspace headings, assessment input, visible controls, and navigation around answer evaluation and teacher review.
- [x] Replace visible OCR-development metrics and text-comparison labels with production assessment metrics and answer-review language.
- [x] Verify all primary views for consistent academic assessment language, then save a checkpoint.

## Centered Hero Assistant

- [x] Center the hero assistant within its right-side visual zone.
- [x] Rebalance the guide and evaluation-status callouts around the centered assistant.
- [x] Verify the desktop and mobile hero composition, then save a checkpoint.

## Configure Page — Frontend Prototype

- [x] Add Configure as the second dashboard navigation item and route it to `/configure`.
- [x] Implement the staged configuration header, lightweight progress indicator, and one-bot guidance system.
- [x] Build mock ZIP upload behavior for student answer papers with progress, completion, change, and remove actions.
- [x] Build mock answer-key upload behavior that activates after answer-paper upload succeeds.
- [x] Add staged class and subject selectors, assessment strictness controls, and configuration review state.
- [x] Keep all upload, grading, and readiness behavior frontend-only without parsing or backend claims.
- [x] Validate desktop and mobile flows, then save a checkpoint.

## Global Inter and Configure Layout Refinement

- [x] Set Inter as the global UI font while preserving mono text only for measured technical values.
- [x] Increase Configure page heading, body, form, and action sizing for clearer hierarchy.
- [x] Rebalance the active Configure layout to fill available desktop height without a large blank lower area.
- [x] Validate desktop and mobile typography and layout, then save a checkpoint.

## Teacher-Managed Classes and Subjects

- [x] Add a frontend-only Add class action that creates and selects a teacher-entered class option.
- [x] Add a frontend-only Add subject action that creates and selects a teacher-entered subject option.
- [x] Validate the new options within Assessment Details and save a checkpoint.

## EvalBot Mascot Replacement

- [x] Prepare the uploaded EvalBot image for use as the shared visual guide.
- [x] Replace the existing hero and Configure guide mascot references with EvalBot.
- [x] Verify EvalBot scale and layout balance at desktop and mobile sizes, then save a checkpoint.

## Transparent Centered EvalBot

- [x] Create a transparent-background EvalBot asset from the uploaded guide illustration.
- [x] Center the transparent EvalBot in the hero visual zone while keeping guide callouts readable.
- [x] Verify desktop and mobile guide composition, then save a checkpoint.

## Exact Hero Guide Centering

- [x] Anchor EvalBot to the exact center of the hero’s right-side visual area.
- [x] Rebalance guide and evaluation callouts around the newly centered character.
- [x] Verify the final hero alignment and save a checkpoint.

## Configure Guide Centering

- [x] Center EvalBot within the Configure guide panel’s lower visual zone.
- [x] Increase EvalBot scale slightly without encroaching on guidance copy or panel edges.
- [x] Verify desktop and mobile guide panel composition, then save a checkpoint.

## Prominent Configure EvalBot

- [x] Enlarge EvalBot within the Configure guide panel’s available visual region.
- [x] Center EvalBot vertically and horizontally beneath the instruction card.
- [x] Verify desktop and mobile guide composition, then save a checkpoint.

## Evaluation Workspace — Frontend Prototype

- [x] Add the `/evaluation` route and active Evaluation navigation state.
- [x] Implement configured-class selection cards and the no-configured-classes empty state.
- [x] Build selected-class review with searchable answer sheets, assessment details, strictness summary, previews, and missing-sheet upload.
- [x] Build a realistic frontend-only evaluation progress workspace with worker, queue, and current-sheet states.
- [x] Build an evaluation-complete state with transparent mock result metrics and a View Results action.
- [x] Validate state transitions, desktop and mobile layouts, then save a checkpoint.

## Evaluation Guide Visibility Fix

- [x] Reposition EvalBot so the compact Evaluation guide card visibly shows the character beside its message.
- [x] Preserve readable guidance copy and the existing compact glass composition.
- [x] Verify the corrected guide card and save a checkpoint.

## Wider Evaluation Guide Card

- [x] Expand the compact Evaluation guide into a wider horizontal card.
- [x] Rebalance the message panel and EvalBot frame so both fit cleanly without clipping.
- [x] Validate desktop and mobile guide composition, then save a checkpoint.

## Evaluation Card Line Alignment

- [x] Remove or relocate decorative card lines that cut through the class-card content.
- [x] Preserve a restrained evidence cue without interfering with card labels or actions.
- [x] Verify the cleaner cards on desktop and mobile, then save a checkpoint.

## Equal Evaluation Card Alignment

- [x] Remove staggered vertical offsets from configured-class cards.
- [x] Apply a uniform card height and aligned baseline across the class row.
- [x] Validate desktop and mobile card alignment, then save a checkpoint.

## Results Workspace — Frontend Prototype

- [x] Add a Results route and active sidebar state after Evaluation.
- [x] Build a completed-assessment class selection view and no-results state.
- [x] Build a searchable, filterable class result roster with frontend-only student result values.
- [x] Build a student overview with question-level marking decisions and review states.
- [x] Add clearly labeled frontend-only evidence placeholders without parsing or OCR claims.
- [x] Validate Results states on desktop and mobile, then save a checkpoint.

## Sidebar Visual Edit Verification

- [x] Identify the stale visual-editor Sidebar target at the current navigation row.
- [x] Remove the Settings Sidebar button and its icon without affecting active app routes.
- [x] Verify the refined rail and save a checkpoint.

## Lower Sidebar Control Removal

- [x] Remove the Answer Sheets, Review, and lower adjustment/settings-style Sidebar controls.
- [x] Remove their unused icon imports and preserve Home, Configure, Evaluation, and Results navigation.
- [x] Verify the simplified rail and save a checkpoint.

## Configure Minimum Word Count

- [x] Add frontend-only minimum word-count rule types and configuration state.
- [x] Add range-based and individual-question word-count controls beside strictness configuration.
- [x] Show the teacher-selected full-mark minimum word counts in the configuration review.
- [x] Validate the expanded Configure flow on desktop and mobile, then save a checkpoint.

## Global Word-Count Policy Step

- [x] Add a fifth Configure progress step for global word-count policy.
- [x] Let teachers choose the shortfall threshold that triggers a deduction and the marks deducted.
- [x] Make the global scope clear and retain the policy in local frontend-only configuration state.
- [x] Surface the policy in configuration review and validate the five-step flow, then save a checkpoint.

## Login and Sign Up Pages

- [x] Inspect existing routes, app shell, and landing-page actions for authentication-page integration.
- [x] Build responsive EvalAI Login and Sign Up pages with labelled frontend-only forms and validation states.
- [x] Connect Login and Sign Up routes to product actions with transparent frontend-only success messages.
- [x] Validate desktop and mobile authentication page layouts and save a checkpoint.

## Teacher Account and Personalized Configuration

- [x] Define centralized frontend-only teacher profile and session state with department-subject mappings.
- [x] Expand Sign Up with validated full name, email, password confirmation, searchable multi-department, and subject selections.
- [x] Add Login validation, remember-me, forgot-password affordance, and frontend-only session behavior.
- [x] Protect dashboard, Configure, Evaluation, Results, and profile routes while preserving public Home and authentication pages.
- [x] Add a header teacher control, sign-out behavior, and a Teaching Profile page with editable departments and subjects.
- [x] Filter Configure subjects according to the signed-in teacher and the selected class department, including an empty-subject state.
- [x] Validate teacher account, profile editing, route protection, and personalized Configure behavior on desktop and mobile.

## Comma-Separated Subject Entry

- [x] Replace the Subjects You Teach multi-select with a teacher-entered comma-separated field in Sign Up and Teaching Profile settings.
- [x] Add clear guidance and validation for one or more comma-separated subject names.
- [x] Preserve the submitted subject names as personalized Configure options and validate the updated flow.

## Teacher Profile Menu Cleanup

- [x] Remove the redundant Settings item beneath Teaching Profile in the header profile menu.
- [x] Preserve the Teaching Profile and Sign Out menu actions.
- [x] Verify the streamlined menu and save a checkpoint.

## Processing Computers Workspace

- [x] Review the Processing Computers requirements and define frontend-only capacity, worker, queue, and health states.
- [x] Add a protected Processing Computers route and dashboard navigation entry.
- [x] Build a responsive processing capacity dashboard with clearly labeled mock operational data.
- [x] Validate the new page on desktop and mobile, then save a checkpoint.

## Global Diagram Policy

- [x] Add frontend-only diagram requirement and deduction-rule state to the global Configure policy.
- [x] Let teachers set the minimum required diagrams and either shared or diagram-specific missing-diagram deductions.
- [x] Clearly explain that diagram order will be collected from the answer key and show the policy in configuration review.
- [x] Validate the adaptive diagram policy at desktop and mobile sizes, then save a checkpoint.

## Half-Mark Global Deductions

- [x] Allow 0.5-mark increments for global word-count and diagram-missing deductions.
- [x] Keep minimum diagram counts limited to whole numbers.
- [x] Validate half-mark policy inputs and review summary text, then save a checkpoint.

## Analytics Workspace — Frontend Prototype

- [x] Define mock class and student analytics data, including charts, insights, score bands, and concept difficulty.
- [x] Add a protected Analytics route and fifth Sidebar item before Computers.
- [x] Build the class-level analytics dashboard, mock chart visuals, filters, and student performance list.
- [x] Add dedicated student analytics with question performance, strengths, and improvement areas.
- [x] Validate Analytics desktop and mobile states, then save a checkpoint.

## Analytics Difficulty and Content Refinement

- [x] Replace Question Performance bars with a colour-coded pie chart that communicates difficulty.
- [x] Remove AI-style class insights, suggested teaching focus, student insights, and revision recommendations.
- [x] Retain only transparent frontend-only academic performance views and validate the refined Analytics workspace.

## Compact Student Analytics Overlay

- [x] Open individual student Analytics in a compact overlay above the current class dashboard.
- [x] Preserve the visible class dashboard and enable a clear close action without navigation.
- [x] Validate the overlay at desktop and mobile widths, then save a checkpoint.

## Responsive Analytics Overlay Refinement

- [x] Refine the student overlay proportions, visual hierarchy, and density for desktop viewports.
- [x] Improve mobile padding, metric-card sizing, chart layout, and safe scrolling within the overlay.
- [x] Validate both responsive compositions and save a checkpoint.

## Question-Specific Diagram Rules

- [x] Add frontend-only diagram rules for individual questions and selected question ranges in Configure.
- [x] Support minimum diagram counts plus shared or answer-key-ordered per-diagram missing deductions within each question rule.
- [x] Surface question-specific diagram rules in the configuration review and validate the responsive flow.

## Global Diagram Policy Removal

- [x] Remove the redundant global Diagram requirement card from Configure Step 5.
- [x] Remove obsolete global diagram state, persistence, and review-summary content.
- [x] Validate the simplified word-count policy and question-specific diagram flow, then save a checkpoint.

## Text-Labelled Glass Dashboard Sidebar

- [x] Replace the narrow icon-only dashboard rail with a taller text-labelled glass sidebar on desktop.
- [x] Preserve all current EvalAI navigation routes, active states, and mobile navigation behavior.
- [x] Validate the revised dashboard shell visually and save a checkpoint.

## Compact Dark Reference Sidebar

- [x] Restyle the desktop sidebar to match the supplied dark rounded navigation reference, including compact type, icon circles, and selected-row treatment.
- [x] Retain EvalAI routes while omitting the reference’s profile and verification cards.
- [x] Validate the reference-led sidebar on desktop and mobile, then save a checkpoint.

## Sidebar Scale and Full-Height Panel

- [x] Increase the compact dark sidebar’s label and supporting text scale for clearer reading.
- [x] Stretch the rounded graphite navigation panel through the full available sidebar height.
- [x] Validate the larger text and full-height treatment, then save a checkpoint.

## Sidebar Footer Cleanup

- [x] Remove the unused Add assessment section line and its icon import from the dark sidebar.
- [x] Validate the simplified panel and save a checkpoint.

## Sidebar Font Increase

- [x] Increase compact dark sidebar navigation label size slightly and preserve visual spacing.
- [x] Validate the enlarged typography and save a checkpoint.

## Prominent Sidebar Typography

- [ ] Make the dark sidebar’s brand and navigation text visibly larger and stronger.
- [ ] Increase row and icon scale to maintain balance around the larger labels.
- [ ] Validate the clearly enlarged sidebar on the dashboard and save a checkpoint.

## Continuous Dashboard Surface

- [x] Extend the dark dashboard sidebar surface cleanly to the full bottom edge of the workspace.
- [x] Preserve the compact navigation layout and rounded outer shell treatment.
- [x] Validate the continuous surface and save a checkpoint.

## Unified Dashboard Shell

- [x] Integrate the dark navigation as a continuous left column inside the primary application shell.
- [x] Remove visual gaps and isolated-card boundaries between the dashboard navigation and main page.
- [x] Validate the unified shell composition and save a checkpoint.

## Persistent Dashboard Navigation

- [x] Keep the dark dashboard navigation pinned while long workspace content scrolls.
- [x] Preserve the unified shell composition and route navigation behavior.
- [x] Validate scrolling visibility and save a checkpoint.

## Sidebar Icon Cleanup and Project Package

- [x] Remove the stale-targeted desktop sidebar menu icon and its unused import.
- [x] Validate the simplified sidebar, save a checkpoint, and package the updated project as a ZIP.

## Question-Specific Word-Count Rules

- [x] Replace the global word-count policy with range and individual-question configuration modes.
- [x] Allow each applicable rule to define full-mark minimum words, a shortfall trigger, and 0.5-mark deduction increments.
- [x] Surface word-count rule details in the configuration review and validate the responsive flow.

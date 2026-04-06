# Playwright MCP Prompt

Use this prior example as a guide for similar tasks.

## Business instruction
You are onboarding a new employee into the Oakridge Workforce legacy HR system. The employee is Victor Ramos (EMP-2042).

Complete the full multi-page onboarding flow end to end:

PERSONAL page:
- First Name: Victor
- Last Name: Ramos
- Preferred Name: (leave blank)
- Email: victor.ramos@oakridge.co
- Phone: 602-555-0146
- Work Mode: Onsite
- Location: Phoenix Distribution Support
- Start Date: 2026-05-11
- Manager: Diego Alvarez
- Employment Type: Part Time

JOB SETUP page:
- Department: Operations
- Role: Operations Specialist
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00
- Background Check Complete: Yes
- I-9 Complete: Yes
- Manager Approval Received: Yes
- Needs Relocation Support: No

PAYROLL page:
- Pay Type: Hourly
- Pay Rate: 29.75
- Payroll Frequency: Biweekly
- Bonus Eligible: No
- Overtime Eligible: Yes
- Direct Deposit Setup: Yes

ACCESS page:
- Laptop Required: No
- VPN Access Required: No
- Badge Access Required: Yes
- Admin Access Level: None

Click Continue / Next to advance through each page. On the Review page, review all data, then click Submit (or equivalent) to submit the onboarding request.

After submission, navigate to the Employees list and verify Victor Ramos appears with:
- Department: Operations
- Role: Operations Specialist
- Pay: 29.75
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00

Then open Victor Ramos's employee record and confirm these onboarding settings are saved:
- Work Mode: Onsite
- Payroll Frequency: Biweekly
- Background Check: Yes/Complete
- I-9 Status: Yes/Complete
- Laptop Required: No
- VPN Access: No
- Badge Access: Yes
- Admin Access Level: None

Report the final result and any issues encountered.

## Execution prompt
Business action: Dynamic Form Flow
Business intent: You are onboarding a new employee into the Oakridge Workforce legacy HR system. The employee is Victor Ramos (EMP-2042).

Complete the full multi-page onboarding flow end to end:

PERSONAL page:
- First Name: Victor
- Last Name: Ramos
- Preferred Name: (leave blank)
- Email: victor.ramos@oakridge.co
- Phone: 602-555-0146
- Work Mode: Onsite
- Location: Phoenix Distribution Support
- Start Date: 2026-05-11
- Manager: Diego Alvarez
- Employment Type: Part Time

JOB SETUP page:
- Department: Operations
- Role: Operations Specialist
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00
- Background Check Complete: Yes
- I-9 Complete: Yes
- Manager Approval Received: Yes
- Needs Relocation Support: No

PAYROLL page:
- Pay Type: Hourly
- Pay Rate: 29.75
- Payroll Frequency: Biweekly
- Bonus Eligible: No
- Overtime Eligible: Yes
- Direct Deposit Setup: Yes

ACCESS page:
- Laptop Required: No
- VPN Access Required: No
- Badge Access Required: Yes
- Admin Access Level: None

Click Continue / Next to advance through each page. On the Review page, review all data, then click Submit (or equivalent) to submit the onboarding request.

After submission, navigate to the Employees list and verify Victor Ramos appears with:
- Department: Operations
- Role: Operations Specialist
- Pay: 29.75
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00

Then open Victor Ramos's employee record and confirm these onboarding settings are saved:
- Work Mode: Onsite
- Payroll Frequency: Biweekly
- Background Check: Yes/Complete
- I-9 Status: Yes/Complete
- Laptop Required: No
- VPN Access: No
- Badge Access: Yes
- Admin Access Level: None

Report the final result and any issues encountered.
Target URL: http://127.0.0.1:4321/#onboarding-personal
Inferred task type: multi_step_submit
Template confidence: 38
Preferred runtime strategy: agentic
Routing rationale: Routing hint is 'agentic' because the task type is 'multi_step_submit', confidence is 38, and the selected template is 'dynamic_form_flow'.

Use the spreadsheet row values below as the source of truth:
- Employee ID: EMP-2042
- Status: Active
- First Name: Victor
- Last Name: Ramos
- Email: victor.ramos@oakridge.co
- Phone: 602-555-0146
- Manager: Diego Alvarez
- Employment Type: Part Time
- Work Mode: Onsite
- Start Date: 2026-05-11
- Location: Phoenix Distribution Support
- Department: Operations
- Role: Operations Specialist
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00
- Background Check Complete: Yes
- I-9 Complete: Yes
- Manager Approval Received: Yes
- Needs Relocation Support: No
- Pay Type: Hourly
- Pay Rate: 29.75
- Payroll Frequency: Biweekly
- Bonus Eligible: No
- Overtime Eligible: Yes
- Direct Deposit Setup: Yes
- Laptop Required: No
- VPN Access Required: No
- Badge Access Required: Yes
- Admin Access Level: None

Execution goals:
1. Reach the relevant working page: Open the target application and navigate to the section where this business task can be completed.
2. Fill mapped fields: Use the spreadsheet-driven field mappings to populate the fields that are present on the page, including multi-step forms.
3. Submit or advance the workflow: Advance or submit the form until the workflow reaches either a success state or a clear next-step state.
4. Verify created record in list: Navigate to the post-submit list and confirm the created record appears with expected identifying details.
5. Verify saved record details: Open the saved record and confirm key persisted details are visible.
6. Verify success state: Confirm that the browser reached a visible success state, a new wizard step, or a persisted outcome before finishing the run.

Execution guidance:
- Open the target URL and inspect the visible page state before taking irreversible actions.
- Use labels, placeholders, nearby section text, tables, dialogs, tabs, and wizard controls to choose the next action.
- Prefer deterministic filling when fields are clearly matched, then switch to broader recovery if the page does not behave as expected.
- Treat multi-step forms as valid progress even before the final success message appears.
- Only update fields that are present in the spreadsheet row unless the site requires a mandatory workflow field.
- Prefer buttons labeled: Submit, Save, Finish, Continue, Review, Next, Create.
- Verify success using text or states such as: saved, submitted, created, completed, confirmation, thank you, application saved successfully.

## Execution goals
1. Reach the relevant working page: Open the target application and navigate to the section where this business task can be completed.
2. Fill mapped fields: Use the spreadsheet-driven field mappings to populate the fields that are present on the page, including multi-step forms.
3. Submit or advance the workflow: Advance or submit the form until the workflow reaches either a success state or a clear next-step state.
4. Verify created record in list: Navigate to the post-submit list and confirm the created record appears with expected identifying details.
5. Verify saved record details: Open the saved record and confirm key persisted details are visible.
6. Verify success state: Confirm that the browser reached a visible success state, a new wizard step, or a persisted outcome before finishing the run.

## Spreadsheet-driven values
- Employee ID: EMP-2042
- Status: Active
- First Name: Victor
- Last Name: Ramos
- Preferred Name: 
- Email: victor.ramos@oakridge.co
- Phone: 602-555-0146
- Manager: Diego Alvarez
- Employment Type: Part Time
- Work Mode: Onsite
- Start Date: 2026-05-11
- Location: Phoenix Distribution Support
- Department: Operations
- Role: Operations Specialist
- Weekly Hours: 36
- Schedule: Tue-Sat 10:00-6:00
- Background Check Complete: Yes
- I-9 Complete: Yes
- Manager Approval Received: Yes
- Needs Relocation Support: No
- Pay Type: Hourly
- Pay Rate: 29.75
- Payroll Frequency: Biweekly
- Bonus Eligible: No
- Overtime Eligible: Yes
- Direct Deposit Setup: Yes
- Laptop Required: No
- VPN Access Required: No
- Badge Access Required: Yes
- Admin Access Level: None

## Normalized values used at runtime
- Employee ID: EMP-2042 (candidates: EMP-2042)
- Status: Active (candidates: Active)
- First Name: Victor (candidates: Victor)
- Last Name: Ramos (candidates: Ramos)
- Email: victor.ramos@oakridge.co (candidates: victor.ramos@oakridge.co)
- Phone: 602-555-0146 (candidates: 602-555-0146, (602) 555-0146, 6025550146)
- Manager: Diego Alvarez (candidates: Diego Alvarez)
- Employment Type: Part Time (candidates: Part Time)
- Work Mode: Onsite (candidates: Onsite)
- Start Date: 2026-05-11 (candidates: 2026-05-11, 5/11/2026)
- Location: Phoenix Distribution Support (candidates: Phoenix Distribution Support)
- Department: Operations (candidates: Operations)
- Role: Operations Specialist (candidates: Operations Specialist)
- Weekly Hours: 36 (candidates: 36)
- Schedule: Tue-Sat 10:00-6:00 (candidates: Tue-Sat 10:00-6:00)
- Background Check Complete: Yes (candidates: Yes, True, true, yes, 1)
- I-9 Complete: Yes (candidates: Yes, True, true, yes, 1)
- Manager Approval Received: Yes (candidates: Yes, True, true, yes, 1)
- Needs Relocation Support: No (candidates: No, False, false, no, 0)
- Pay Type: Hourly (candidates: Hourly)
- Pay Rate: 29.75 (candidates: 29.75)
- Payroll Frequency: Biweekly (candidates: Biweekly)
- Bonus Eligible: No (candidates: No, False, false, no, 0)
- Overtime Eligible: Yes (candidates: Yes, True, true, yes, 1)
- Direct Deposit Setup: Yes (candidates: Yes, True, true, yes, 1)
- Laptop Required: No (candidates: No, False, false, no, 0)
- VPN Access Required: No (candidates: No, False, false, no, 0)
- Badge Access Required: Yes (candidates: Yes, True, true, yes, 1)
- Admin Access Level: None (candidates: None)

## Safety guidance
- Only edit fields that are present in the spreadsheet row.
- Capture screenshots during important page transitions and after the final outcome.
- Reuse the same target application and workflow when performing similar tasks.
- If labels differ, use nearby visible text or placeholders that clearly match the spreadsheet column headers.
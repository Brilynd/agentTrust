# Playwright MCP Prompt

Use this prior example as a guide for similar tasks.

## Business instruction
You are on a car insurance portal. Navigate to the new policyholder form and add Jordan Reyes using all data from the spreadsheet row. Submit when done.

## Execution prompt
Business action: Create Record
Business intent: You are on a car insurance portal. Navigate to the new policyholder form and add Jordan Reyes using all data from the spreadsheet row. Submit when done.
Target URL: file:///C:/Users/madey/OneDrive/Desktop/newagenttrust/business-rpa-assistant/mock-apps/car-insurance-portal/index.html
Inferred task type: create
Template confidence: 30
Preferred runtime strategy: hybrid
Routing rationale: Routing hint is 'hybrid' because the task type is 'create', confidence is 30, and the selected template is 'create_record'.

Use the spreadsheet row values below as the source of truth:
- Email: jordan.reyes@email.com
- Phone: 512-555-0441
- Status: New Intake
- Notes: New customer relocated from Dallas. Works hybrid schedule and parks in secured apartment garage.
- Customer ID: AUTO-31001
- First Name: Jordan
- Last Name: Reyes
- Date of Birth: 1990-08-13
- Driver License Number: R7654321
- Driver License State: TX
- Preferred Contact Method: Email
- Address: 4108 Barton Hills Drive
- City: Austin
- State: TX
- Postal Code: 78704
- Vehicle Year: 2023
- Vehicle Make: Toyota
- Vehicle Model: Camry XSE
- Vehicle VIN: 4T1K61AK2PU781204
- Annual Mileage: 12000
- Current Carrier: Progressive
- Coverage Tier: Preferred
- Liability Limit: 100/300/100
- Collision Deductible: $500
- Comprehensive Deductible: $250
- Policy Effective Date: 2026-04-14
- Payment Plan: Monthly EFT

Execution goals:
1. Reach the relevant working page: Open the target application and navigate to the section where this business task can be completed.
2. Fill mapped fields: Use the spreadsheet-driven field mappings to populate the fields that are present on the page, including multi-step forms.
3. Submit or advance the workflow: Advance or submit the form until the workflow reaches either a success state or a clear next-step state.
4. Verify success state: Confirm that the browser reached a visible success state, a new wizard step, or a persisted outcome before finishing the run.

Execution guidance:
- Open the target URL and inspect the visible page state before taking irreversible actions.
- Use labels, placeholders, nearby section text, tables, dialogs, tabs, and wizard controls to choose the next action.
- Prefer deterministic filling when fields are clearly matched, then switch to broader recovery if the page does not behave as expected.
- Treat multi-step forms as valid progress even before the final success message appears.
- Only update fields that are present in the spreadsheet row unless the site requires a mandatory workflow field.
- Prefer buttons labeled: Save Application, Submit, Save, Create, Create New Policyholder.
- Verify success using text or states such as: created, saved, submitted, success, application saved successfully.

## Execution goals
1. Reach the relevant working page: Open the target application and navigate to the section where this business task can be completed.
2. Fill mapped fields: Use the spreadsheet-driven field mappings to populate the fields that are present on the page, including multi-step forms.
3. Submit or advance the workflow: Advance or submit the form until the workflow reaches either a success state or a clear next-step state.
4. Verify success state: Confirm that the browser reached a visible success state, a new wizard step, or a persisted outcome before finishing the run.

## Spreadsheet-driven values
- Customer ID: AUTO-31001
- Status: New Intake
- First Name: Jordan
- Last Name: Reyes
- Email: jordan.reyes@email.com
- Phone: 512-555-0441
- Date of Birth: 1990-08-13
- Driver License Number: R7654321
- Driver License State: TX
- Preferred Contact Method: Email
- Address: 4108 Barton Hills Drive
- City: Austin
- State: TX
- Postal Code: 78704
- Vehicle Year: 2023
- Vehicle Make: Toyota
- Vehicle Model: Camry XSE
- Vehicle VIN: 4T1K61AK2PU781204
- Annual Mileage: 12000
- Current Carrier: Progressive
- Coverage Tier: Preferred
- Liability Limit: 100/300/100
- Collision Deductible: $500
- Comprehensive Deductible: $250
- Policy Effective Date: 2026-04-14
- Payment Plan: Monthly EFT
- Notes: New customer relocated from Dallas. Works hybrid schedule and parks in secured apartment garage.
- __EMPTY: 

## Normalized values used at runtime
- Email: jordan.reyes@email.com (candidates: jordan.reyes@email.com)
- Phone: 512-555-0441 (candidates: 512-555-0441, (512) 555-0441, 5125550441)
- Status: New Intake (candidates: New Intake)
- Notes: New customer relocated from Dallas. Works hybrid schedule and parks in secured apartment garage. (candidates: New customer relocated from Dallas. Works hybrid schedule and parks in secured apartment garage.)
- Customer ID: AUTO-31001 (candidates: AUTO-31001)
- First Name: Jordan (candidates: Jordan)
- Last Name: Reyes (candidates: Reyes)
- Date of Birth: 1990-08-13 (candidates: 1990-08-13, 8/13/1990)
- Driver License Number: R7654321 (candidates: R7654321)
- Driver License State: TX (candidates: TX)
- Preferred Contact Method: Email (candidates: Email)
- Address: 4108 Barton Hills Drive (candidates: 4108 Barton Hills Drive)
- City: Austin (candidates: Austin)
- State: TX (candidates: TX)
- Postal Code: 78704 (candidates: 78704)
- Vehicle Year: 2023 (candidates: 2023)
- Vehicle Make: Toyota (candidates: Toyota)
- Vehicle Model: Camry XSE (candidates: Camry XSE)
- Vehicle VIN: 4T1K61AK2PU781204 (candidates: 4T1K61AK2PU781204)
- Annual Mileage: 12000 (candidates: 12000)
- Current Carrier: Progressive (candidates: Progressive)
- Coverage Tier: Preferred (candidates: Preferred)
- Liability Limit: 100/300/100 (candidates: 100/300/100)
- Collision Deductible: $500 (candidates: $500)
- Comprehensive Deductible: $250 (candidates: $250)
- Policy Effective Date: 2026-04-14 (candidates: 2026-04-14, 4/14/2026)
- Payment Plan: Monthly EFT (candidates: Monthly EFT)

## Safety guidance
- Only edit fields that are present in the spreadsheet row.
- Capture screenshots during important page transitions and after the final outcome.
- Reuse the same target application and workflow when performing similar tasks.
- If labels differ, use nearby visible text or placeholders that clearly match the spreadsheet column headers.
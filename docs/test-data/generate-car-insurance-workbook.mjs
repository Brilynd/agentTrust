import path from "node:path";
import { fileURLToPath } from "node:url";

import xlsx from "xlsx";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const rows = [
  {
    "Customer ID": "AUTO-31001",
    "Status": "New Intake",
    "First Name": "Jordan",
    "Last Name": "Reyes",
    "Email": "jordan.reyes@email.com",
    "Phone": "512-555-0441",
    "Date of Birth": "1990-08-14",
    "Driver License Number": "R7654321",
    "Driver License State": "TX",
    "Preferred Contact Method": "Email",
    "Address": "4108 Barton Hills Drive",
    "City": "Austin",
    "State": "TX",
    "Postal Code": "78704",
    "Vehicle Year": "2023",
    "Vehicle Make": "Toyota",
    "Vehicle Model": "Camry XSE",
    "Vehicle VIN": "4T1K61AK2PU781204",
    "Annual Mileage": "12000",
    "Current Carrier": "Progressive",
    "Coverage Tier": "Preferred",
    "Liability Limit": "100/300/100",
    "Collision Deductible": "$500",
    "Comprehensive Deductible": "$250",
    "Policy Effective Date": "2026-04-15",
    "Payment Plan": "Monthly EFT",
    "Notes": "New customer relocated from Dallas. Works hybrid schedule and parks in secured apartment garage."
  },
  {
    "Customer ID": "AUTO-31002",
    "Status": "Pending Underwriting",
    "First Name": "Madison",
    "Last Name": "Clark",
    "Email": "m.clark@outlook.com",
    "Phone": "737-555-0176",
    "Date of Birth": "1985-12-03",
    "Driver License Number": "C2198437",
    "Driver License State": "TX",
    "Preferred Contact Method": "Phone",
    "Address": "1712 Westview Ridge",
    "City": "Georgetown",
    "State": "TX",
    "Postal Code": "78628",
    "Vehicle Year": "2024",
    "Vehicle Make": "Subaru",
    "Vehicle Model": "Outback Touring",
    "Vehicle VIN": "4S4BTGPD5R3251842",
    "Annual Mileage": "15000",
    "Current Carrier": "USAA",
    "Coverage Tier": "Premium",
    "Liability Limit": "250/500/250",
    "Collision Deductible": "$500",
    "Comprehensive Deductible": "$500",
    "Policy Effective Date": "2026-05-01",
    "Payment Plan": "Paid in Full",
    "Notes": "Prior carrier reported one comprehensive windshield claim in 2024. Requesting bundled home quote later."
  },
  {
    "Customer ID": "AUTO-31003",
    "Status": "Quoted",
    "First Name": "Ethan",
    "Last Name": "Singh",
    "Email": "ethan.singh@gmail.com",
    "Phone": "512-555-0299",
    "Date of Birth": "1993-05-26",
    "Driver License Number": "S4431908",
    "Driver License State": "TX",
    "Preferred Contact Method": "Text",
    "Address": "9220 Willow Pass Lane",
    "City": "Pflugerville",
    "State": "TX",
    "Postal Code": "78660",
    "Vehicle Year": "2022",
    "Vehicle Make": "Ford",
    "Vehicle Model": "Bronco Sport Badlands",
    "Vehicle VIN": "3FMCR9D96NRD44182",
    "Annual Mileage": "9000",
    "Current Carrier": "GEICO",
    "Coverage Tier": "Standard",
    "Liability Limit": "100/300/100",
    "Collision Deductible": "$1,000",
    "Comprehensive Deductible": "$500",
    "Policy Effective Date": "2026-05-10",
    "Payment Plan": "Quarterly Installments",
    "Notes": "Recently added spouse as occasional driver. Wants roadside and rental reimbursement reviewed before binding."
  }
];

const workbook = xlsx.utils.book_new();
const worksheet = xlsx.utils.json_to_sheet(rows);
xlsx.utils.book_append_sheet(workbook, worksheet, "New Customers");

const outputPath = path.join(__dirname, "car-insurance-new-customers.xlsx");
xlsx.writeFile(workbook, outputPath);

console.log(`Wrote ${outputPath}`);

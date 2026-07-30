# Supplier Matching and Email Automation

## Overview
Supplier Matching and Email Automation is a streamlined, AI-powered web application built with Streamlit. The application allows businesses to upload their product requirements and supplier catalogs, automatically matching them based on product categories. It leverages the Groq API (using the LLaMA 3.1 model) to dynamically generate personalized, professional inquiry emails to suppliers, and manages sending these emails via SMTP. Additionally, it tracks sent emails and monitors the user's inbox (via IMAP) for supplier replies, offering both manual and automatic fetch capabilities.

## Features
- **User Information Collection:** Securely input your personal and company details to customize outbound emails.
- **CSV Data Uploads:** Easily upload product requirements and supplier lists in CSV format.
- **Intelligent Category Matching:** Automatically groups products and suppliers by cleaning and matching their category columns.
- **AI Email Generation:** Generates concise, context-aware emails asking critical questions (delivery date, available quantity, payment terms, and return policies) using Groq AI.
- **Automated Email Dispatch:** Sends emails directly from the application through Gmail's SMTP servers and timestamps the event.
- **Reply Tracking:** Scans your Gmail inbox for replies from contacted suppliers and alerts you when a response is received. Supports both on-demand checks and configurable auto-fetching.

## Prerequisites
- Python 3.7+
- A Gmail account with an **App Password** generated (standard passwords will not work for SMTP/IMAP).
- A valid **Groq API Key**.

## Installation

1. **Clone or Download the Repository:**
   Navigate to the project directory:
   ```bash
   cd C:\Users\theba\Downloads\Sales\EMAIL
   ```

2. **Install Dependencies:**
   Install the required Python packages using pip:
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup:**
   Create a `.env` file in the root directory (if it doesn't already exist) and populate it with your credentials:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   EMAIL_ADDRESS=your_gmail_address@gmail.com
   EMAIL_PASSWORD=your_gmail_app_password
   ```

## Detailed Workflow / Flow

### Step 1: Information & Uploads (Tab 1)
- **User Inputs:** The user enters their Name, Company Name, and Location. This data is used to contextualize the generated emails.
- **Data Upload:** The user uploads two CSV files:
  - **Products CSV:** Must contain a column indicating the category (e.g., 'Category' or 'Cat'). It lists the items the user is looking to source.
  - **Sellers CSV:** Must also contain a matching category column along with supplier names and emails.
- **Initialization:** Upon clicking "Start Process", the app proceeds to the next tab, storing the status in the session state.

### Step 2: Suppliers & Products Processing (Tab 2)
- **Data Cleaning:** The app reads the uploaded CSVs, standardizing column names (lowercase, stripping whitespaces) to effortlessly identify the category columns.
- **Categorization:** Products and sellers are grouped into expandable sections based on their specific categories.
- **Review:** Users can view the exact products needed and the available sellers for each respective category.

### Step 3: Email Generation & Dispatch
- **Action Trigger:** Inside a category expander, the user clicks "Generate & Send Emails".
- **AI Prompting:** The app constructs a prompt containing the user's details, seller's name, category, and aggregated product descriptions.
- **Groq API Call:** The prompt is sent to the Groq API (LLaMA 3.1) which returns a tailored, professional email body.
- **SMTP Sending:** The app connects to `smtp.gmail.com` using the provided credentials, dispatches the email to the supplier, and records the exact timestamp in a local file (`sent_timestamps.json`).

### Step 4: Tracking Replies
- **Manual Checking:** Users can click "Check Replies" for a specific category. The app logs into `imap.gmail.com`, retrieves the most recent emails, and checks if any sender matches the contacted suppliers.
- **Time Validation:** It ensures the reply was received *after* the initial inquiry email was sent.
- **Auto-Fetch:** Users can enable "Start Auto-Fetch" and configure an interval (e.g., every 5 minutes). The app will automatically refresh and check for new supplier replies in the background, showing a success marker (✅) when a reply is detected and a waiting marker (⏳) otherwise.

## Technologies Used
- **Streamlit:** Frontend UI and application state management.
- **Pandas:** CSV data manipulation and cleaning.
- **Groq API (LLaMA 3.1):** Natural language generation for dynamic emails.
- **smtplib & imaplib:** Standard Python libraries for sending and reading emails.
- **python-dotenv:** Environment variable management.
- **streamlit-autorefresh:** Automates the page reloading for the auto-fetch feature.

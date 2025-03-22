import streamlit as st
import pandas as pd
import plotly.express as px
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import sqlite3
import os
from datetime import datetime, timedelta
from io import BytesIO
from fuzzywuzzy import fuzz, process
import pkg_resources
from PyPDF2 import PdfReader, PdfWriter
import zipfile
import logging

# Set up logging
logging.basicConfig(filename='./processing.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Set page config
st.set_page_config(page_title="KNORKA 1.0", layout="wide")

# Custom CSS
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
    .stApp {
        background-color: #f0f4f8;
        color: #2c3e50;
        font-family: 'Roboto', sans-serif;
    }
    .header {
        font-size: 32px;
        font-weight: 700;
        color: #ffffff;
        text-align: center;
        background: linear-gradient(90deg, #3498db, #2980b9);
        padding: 10px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    .summary-card {
        background: linear-gradient(135deg, #3498db, #2980b9);
        color: #ffffff;
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        margin-bottom: 15px;
        text-align: center;
    }
    .staff-box {
        background: linear-gradient(135deg, #ecf0f1, #bdc3c7);
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        margin: 5px;
        text-align: center;
        transition: transform 0.2s;
        width: 180px;
        height: 180px;
        display: inline-block;
        vertical-align: top;
        border-left: 4px solid #3498db;
    }
    .staff-box:hover {
        transform: scale(1.05);
    }
    .staff-box h3 {
        font-size: 16px;
        font-weight: 700;
        color: #2c3e50;
        margin-bottom: 5px;
    }
    .staff-box p {
        font-size: 12px;
        margin: 3px 0;
        color: #34495e;
    }
    .top-salesman {
        background: linear-gradient(135deg, #ecf0f1, #bdc3c7);
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        margin: 5px;
        text-align: center;
        border-left: 4px solid #3498db;
    }
    .top-salesman h3 {
        font-size: 16px;
        font-weight: 700;
        color: #2c3e50;
        margin-bottom: 5px;
    }
    .red-text {
        color: #e74c3c;
    }
    </style>
""", unsafe_allow_html=True)

# Password Dictionary
passwords = {
    "Gaurav": "0007855076", "Prakash": "0015102458", "Kishore": "0015102420",
    "Sonu": "0007857305", "Shivam": "0015102456", "Hemant": "0015102447",
    "Sahil": "0007857872", "Arjun": "0015032010", "Vivek": "0007856700",
    "Shum": "0007857811", "Vinod": "0015032022", "Prince": "123456789",
    "Rakesh": "0007857282"
}

# Database Setup with Migration
conn = sqlite3.connect("./incentive_data.db", check_same_thread=False)
cursor = conn.cursor()

# Define the latest table structure
cursor.execute('''CREATE TABLE IF NOT EXISTS incentives
                  (date TEXT, name TEXT, role TEXT, incentive REAL, gross REAL, net_amount REAL, status TEXT, bill_no TEXT, item_name TEXT, company TEXT, qty REAL, rate REAL, second_agent TEXT, parts_count INTEGER, total_pool REAL, item_code TEXT, additional_item_code TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS payments
                  (date TEXT, name TEXT, amount REAL, cleared_date TEXT)''')

# Check and migrate existing table if needed
cursor.execute("PRAGMA table_info(incentives)")
columns = [col[1] for col in cursor.fetchall()]
if "item_code" not in columns:
    cursor.execute("ALTER TABLE incentives ADD COLUMN item_code TEXT")
    logging.info("Added item_code column to incentives table")
if "additional_item_code" not in columns:
    cursor.execute("ALTER TABLE incentives ADD COLUMN additional_item_code TEXT")
    logging.info("Added additional_item_code column to incentives table")
conn.commit()

# Staff List and Roles
staff_list = {
    "Gaurav": "Salesman", "Prakash": "Salesman", "Kishore": "Salesman",
    "Hemant": "Salesman", "Vivek": "Salesman", "Shum": "Salesman",
    "Vinod": "Salesman", "Rakesh": "Salesman", "Maanik": "General",
    "Sahil": "Helper", "Arjun": "Helper", "Shivam": "Helper",
    "Sonu": "Stockboy", "Prince": "Helper"
}
known_staff = [name for name in staff_list.keys() if name != "Maanik"]
known_helpers = [name.lower() for name, role in staff_list.items() if role == "Helper"]
excluded_names = ["Maanik", "NIL"]

# Helper Pool Tracker
helper_pool = 0.0
present_helpers = {}
inactive_salesmen = {}
unique_dates = set()

# Commission Rules
def calculate_incentive(salesman1, salesman2, helper, gross, item_name, net_amount):
    global helper_pool
    total_incentive = net_amount * 0.01  # 1% of net amount
    incentives = {}
    net_amounts = {}

    special_items = ["PETI", "PETICOT", "UNDERWEAR", "INNERWEAR", "JOCKEY"]
    is_special_item = False
    if item_name:
        for special_item in special_items:
            if fuzz.partial_ratio(item_name.lower(), special_item.lower()) >= 80:
                is_special_item = True
                break

    if is_special_item:
        helper_pool += total_incentive
        logging.info(f"{item_name} matched as special item, added {total_incentive} to helper pool")
    else:
        pool_contribution = net_amount * 0.0005
        helper_pool += pool_contribution
        remaining_incentive = total_incentive - pool_contribution

        if salesman1 and not salesman2 and not helper:
            if salesman1.lower() not in excluded_names:
                incentives[salesman1] = remaining_incentive
                net_amounts[salesman1] = net_amount
        elif salesman1 and salesman2:
            if salesman1.lower() not in excluded_names and salesman2.lower() not in excluded_names:
                net_amounts[salesman1] = net_amount
                net_amounts[salesman2] = net_amount
                if salesman2.lower() in ["sonu", "shivam"]:
                    incentives[salesman1] = net_amount * 0.00675
                    incentives[salesman2] = net_amount * 0.00275
                else:
                    incentives[salesman1] = net_amount * 0.00475
                    incentives[salesman2] = net_amount * 0.00475
        elif helper and not salesman1 and not salesman2:
            if helper.lower() not in excluded_names:
                incentives[helper] = remaining_incentive
                net_amounts[helper] = net_amount

    return incentives, net_amounts

# Determine Company
def determine_company(file):
    file_base = os.path.splitext(file.name)[0].split("_")[0]
    if "LS" in file_base:
        return "Life Style"
    elif "NFS" in file_base:
        return "New Fashion Style"
    return "Unknown"

# Normalize Date
def normalize_date(date_str):
    try:
        for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(str(date_str), fmt).strftime("%d-%m-%Y")
            except ValueError:
                continue
        logging.error(f"Unable to parse date {date_str}. Using current date.")
        return datetime.now().strftime("%d-%m-%Y")
    except Exception as e:
        logging.error(f"Error normalizing date {date_str}: {e}")
        return datetime.now().strftime("%d-%m-%Y")

# Encrypt PDF
def encrypt_pdf(input_path, output_path, password):
    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        with open(output_path, "wb") as f:
            writer.write(f)
        logging.info(f"Encrypted PDF: {output_path}")
    except Exception as e:
        logging.error(f"Error encrypting PDF {input_path}: {e}")
        raise

# Process Files
def process_files(erp_files, attendance_file):
    global helper_pool, present_helpers, inactive_salesmen, unique_dates
    if len(erp_files) != 2 or not attendance_file:
        st.error("Please upload exactly 2 ERP files (LS_Sales, NFS_Sales) and 1 Attendance file")
        logging.error("Incorrect number of ERP or missing attendance file")
        return
    
    erp_dfs = []
    for file in erp_files:
        df = pd.read_excel(file, skiprows=2)
        company = determine_company(file)
        erp_dfs.append((file, company, df))
    
    if len([c for _, c, _ in erp_dfs if c in ["Life Style", "New Fashion Style"]]) != 2:
        st.error("Could not identify LS_Sales and NFS_Sales files")
        logging.error("Failed to identify LS_Sales and NFS_Sales files")
        return
    
    erp_dfs.sort(key=lambda x: x[1])
    erp1_file, erp1_company, erp1 = [x for x in erp_dfs if x[1] == "Life Style"][0]
    erp2_file, erp2_company, erp2 = [x for x in erp_dfs if x[1] == "New Fashion Style"][0]
    
    try:
        erp1 = pd.read_excel(erp1_file, skiprows=2)
        erp2 = pd.read_excel(erp2_file, skiprows=2)
        attendance = pd.read_excel(attendance_file, skiprows=6)
    except Exception as e:
        st.error(f"Error loading files: {e}")
        logging.error(f"Error loading files: {e}")
        return
    
    for df in [erp1, erp2, attendance]:
        df.columns = df.columns.str.strip()
        if "AGENT NAME" in df.columns:
            df["AGENT NAME"] = df["AGENT NAME"].apply(lambda x: str(x).strip().replace("\n", "").title() if pd.notna(x) else None)
        if "OTHER AGENT NAME" in df.columns:
            df["OTHER AGENT NAME"] = df["OTHER AGENT NAME"].apply(lambda x: str(x).strip().replace("\n", "").title() if pd.notna(x) else None)
        if "Name" in df.columns:
            df["Name"] = df["Name"].apply(lambda x: str(x).strip().replace("\n", "").title() if pd.notna(x) else None)
    
    if "SNO." not in erp1.columns or "SNO." not in erp2.columns:
        st.error("Column 'SNO.' not found in ERP files")
        logging.error("Column 'SNO.' not found in ERP files")
        return
    
    erp1 = erp1[pd.to_numeric(erp1["SNO."], errors='coerce').notna()]
    erp2 = erp2[pd.to_numeric(erp2["SNO."], errors='coerce').notna()]
    
    if "Name" not in attendance.columns or "Status" not in attendance.columns:
        st.error("Required columns 'Name' or 'Status' not found in Attendance file")
        logging.error("Required columns 'Name' or 'Status' not found in Attendance file")
        return
    
    present_employees = {name.lower(): True for name in attendance[attendance["Status"].isin(["P", "A"])]["Name"] if name is not None}
    logging.info(f"Present employees: {list(present_employees.keys())}")
    
    total_rows_processed = 0
    sales_by_salesman = {}
    unique_dates = set()
    for df, company_prefix in [(erp1, "Life Style"), (erp2, "New Fashion Style")]:
        for index, row in df.iterrows():
            date = row.get("BILL DATE")
            gross = row.get("GROSS AMOUNT", 0)
            net_amount = row.get("NET AMOUNT", row.get("NET AMT", gross * 0.95))
            salesman1 = row.get("AGENT NAME")
            salesman2 = row.get("OTHER AGENT NAME")
            bill_no = row.get("BILL NO.")
            item_name = row.get("ITEM NAME")
            qty = row.get("TOTAL QTY", 1.0)
            rate = row.get("RATE/UNIT", gross / qty if qty > 0 else gross)
            item_code = row.get("ITEM CODE", "")
            additional_item_code = row.get("ADDITIONAL ITEM CODE", "")
            
            if not all([pd.notna(date), gross, pd.notna(bill_no), pd.notna(item_name)]):
                logging.warning(f"Skipped row {index} due to missing data")
                continue
            
            date = normalize_date(date)
            company = company_prefix
            unique_dates.add(date)
            
            helper = None
            salesman1_lower = salesman1.lower() if salesman1 and isinstance(salesman1, str) else None
            salesman2_lower = salesman2.lower() if salesman2 and isinstance(salesman2, str) else None
            
            salesman1 = salesman1 if salesman1_lower and salesman1_lower in [name.lower() for name in known_staff] else None
            if not salesman1 and salesman1_lower:
                best_match, score = process.extractOne(salesman1_lower, [name.lower() for name in known_staff], scorer=fuzz.partial_ratio)
                if score >= 80:
                    salesman1 = next((name for name in known_staff if name.lower() == best_match), None)
                    logging.info(f"Fuzzy matched {salesman1_lower} to {salesman1}")
            
            salesman2 = salesman2 if salesman2_lower and salesman2_lower in [name.lower() for name in known_staff] else None
            if not salesman2 and salesman2_lower:
                best_match, score = process.extractOne(salesman2_lower, [name.lower() for name in known_staff], scorer=fuzz.partial_ratio)
                if score >= 80:
                    salesman2 = next((name for name in known_staff if name.lower() == best_match), None)
                    logging.info(f"Fuzzy matched {salesman2_lower} to {salesman2}")
            
            if not salesman1 and not salesman2 and not helper:
                continue
            
            if salesman1 and salesman1.lower() == "nil":
                if salesman1_lower in present_employees and salesman1 not in sales_by_salesman.get(date, []):
                    inactive_salesmen[salesman1] = inactive_salesmen.get(salesman1, 0) + 1
                continue
            
            incentives, net_amounts = calculate_incentive(salesman1, salesman2, helper, gross, item_name, net_amount)
            for name, amount in incentives.items():
                actual_name = next((staff for staff in known_staff if staff.lower() == name.lower()), name)
                role = staff_list.get(actual_name, "Staff")
                if actual_name.lower() in known_helpers and (salesman1 == actual_name or salesman2 == actual_name):
                    role = "Salesman"
                status = "Present" if actual_name.lower() in present_employees else "Sus"
                if actual_name.lower() not in present_employees:
                    status = f'<span class="red-text">{status}</span>'
                net_amount = net_amounts.get(name, net_amount)
                second_agent = None
                if salesman1 and salesman2:
                    if actual_name == salesman1:
                        second_agent = salesman2
                    elif actual_name == salesman2:
                        second_agent = salesman1
                parts_count = 0
                total_pool = 0.0
                cursor.execute("INSERT INTO incentives VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (date, actual_name, role, amount, gross, net_amount, status, bill_no, item_name, company, qty, rate, second_agent, parts_count, total_pool, item_code, additional_item_code))
                logging.info(f"Inserted incentive for {actual_name} on {date}")
                total_rows_processed += 1
                sales_by_salesman.setdefault(date, []).append(actual_name)

    for date in unique_dates:
        attendance_names = [name.lower() for name in attendance[attendance["Status"].isin(["P", "A"])]["Name"] if name]
        fuzzy_matched_helpers = []
        for att_name in attendance_names:
            best_match, score = process.extractOne(att_name, known_helpers, scorer=fuzz.partial_ratio)
            if score >= 80:
                fuzzy_matched_helpers.append(best_match)
        present_helpers[date] = fuzzy_matched_helpers
        if present_helpers.get(date):
            num_present_helpers = len(present_helpers[date])
            if num_present_helpers > 0:
                total_pool = helper_pool
                pool_share = helper_pool / num_present_helpers if helper_pool > 0 else 1.79
                for helper in present_helpers[date]:
                    actual_helper = next((staff for staff in known_staff if staff.lower() == helper), helper.title())
                    cursor.execute("INSERT INTO incentives VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (date, actual_helper, "Helper", pool_share, 0, 0, "Present", "Helper Pool", "Helper Pool Share", "", 0, 0, None, num_present_helpers, total_pool, "", ""))
                    logging.info(f"Distributed pool incentive {pool_share} to {actual_helper}")

    for salesman, count in inactive_salesmen.items():
        current_week = datetime.strptime("12/03/2025", "%d/%m/%Y").isocalendar()[1]
        if count >= 3 and current_week in [datetime.strptime(d, "%d-%m-%Y").isocalendar()[1] for d in sales_by_salesman.keys()]:
            st.warning(f"{salesman} has not made sales 3 times this week!")
            logging.warning(f"{salesman} has not made sales 3 times this week!")

    st.write(f"Processing completed: {total_rows_processed} rows processed")
    helper_pool = 0.0
    conn.commit()
    
    cursor.execute("SELECT MAX(date) FROM incentives")
    latest_date = cursor.fetchone()[0]
    if latest_date:
        global report_date
        report_date = latest_date
    else:
        report_date = datetime.now().strftime("%d-%m-%Y")
    
    generate_pdfs_to_folder()
    st.success("Files processed and PDFs generated!")

# Original PDF Generation (Restored)
def generate_pdfs_to_folder(selected_date=None, start_date=None, end_date=None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdfs_dir = os.path.join(base_dir, "pdfs")
    if not os.path.exists(pdfs_dir):
        os.makedirs(pdfs_dir)

    for staff in known_staff:
        staff_dir = os.path.join(pdfs_dir, staff)
        if not os.path.exists(staff_dir):
            os.makedirs(staff_dir)

        temp_path = os.path.join(staff_dir, f"{staff}_temp_incentive_report.pdf")
        date_to_use = selected_date.strftime("%d-%m-%Y") if selected_date else report_date if not start_date else f"{start_date.strftime('%d-%m-%Y')}_to_{end_date.strftime('%d-%m-%Y')}"
        output_path = os.path.join(staff_dir, f"{staff}_{date_to_use}_incentive_report.pdf")
        try:
            c = canvas.Canvas(temp_path, pagesize=letter)
        except Exception as e:
            st.error(f"Error creating canvas for {staff}: {e}")
            continue

        styles = getSampleStyleSheet()
        width, height = letter
        y_position = height - 70
        page_number = 1

        if selected_date or not start_date:
            date_dt = datetime.strptime(date_to_use, "%d-%m-%Y")
            day_of_week = date_dt.strftime("%A").upper()
            header_date = date_to_use.replace('-', '/')
        else:
            date_dt = end_date
            day_of_week = date_dt.strftime("%A").upper()
            header_date = f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"

        c.setFont("Helvetica-Bold", 12)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.drawString(50, y_position, f"Salesman Name: {staff.upper()}    Incentive Date: {header_date} - {day_of_week}")

        role = staff_list.get(staff, "Staff")
        if role == "Helper":
            cursor.execute("SELECT total_pool FROM incentives WHERE name = ? AND bill_no = 'Helper Pool' AND date = ?", (staff, date_to_use if not start_date else end_date.strftime("%d-%m-%Y")))
            total_pool_data = cursor.fetchone()
            total_pool = total_pool_data[0] if total_pool_data and total_pool_data[0] is not None else 0.0
            y_position -= 20
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(50, y_position, f"Total Helper Pool for the Day: Rs.{total_pool:.2f}")

        try:
            if not start_date:
                cursor.execute("SELECT bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool FROM incentives WHERE name = ? AND date = ?", (staff, date_to_use))
            else:
                cursor.execute("SELECT bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool FROM incentives WHERE name = ? AND date BETWEEN ? AND ?", (staff, start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            bill_data = cursor.fetchall()
        except Exception as e:
            st.error(f"Error querying data for {staff}: {e}")
            bill_data = []

        table_headers = ["Bill No", "Item", "Qty", "Rate", "Amount", "Second Agent", "%", "Incentive"]
        table_data = [table_headers]
        total_net_amount = 0
        total_incentive = 0
        total_bills = set()

        for row in bill_data:
            if row:
                bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool = row
                percent = (incentive / net_amount) * 100 if net_amount != 0 else 0
                rate_str = f"Rs.{rate:.2f}" if rate != 0 else "Rs.0.00"
                amount_str = f"Rs.{net_amount:.2f}" if net_amount != 0 else "Rs.0.00"
                incentive_str = f"Rs.{incentive:.2f}"
                second_agent_display = second_agent if second_agent else "N/A"
                table_data.append([bill_no, item_name, f"{qty:.1f}", rate_str, amount_str, second_agent_display, f"{percent:.3f}%", incentive_str])
                total_net_amount += net_amount
                total_incentive += incentive
                if bill_no != "Helper Pool":
                    total_bills.add(bill_no)

        if not bill_data:
            y_position -= 40
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(50, y_position, f"No data available for {staff} on {header_date}")
        else:
            try:
                table = Table(table_data, colWidths=[70, 100, 50, 60, 60, 80, 50, 60])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5f5f5')),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                table.wrapOn(c, width - 100, height)
                table_height = table._height
                y_position -= table_height + 20
                table.drawOn(c, 50, y_position)
            except Exception as e:
                st.error(f"Error drawing table for {staff}: {e}")
                continue

        month_start = date_dt.replace(day=1).strftime("%d-%m-%Y")
        cursor.execute("SELECT SUM(net_amount), SUM(incentive) FROM incentives WHERE name = ? AND date BETWEEN ? AND ?", (staff, month_start, date_to_use if not start_date else end_date.strftime("%d-%m-%Y")))
        month_totals = cursor.fetchone()
        total_month_net_amount = month_totals[0] if month_totals and month_totals[0] is not None else 0.0
        total_month_incentive = month_totals[1] if month_totals and month_totals[1] is not None else 0.0

        summary_data = [
            ["Sale (Current PDF)", f"Rs.{total_net_amount:.2f}"],
            ["Incentive (Current PDF)", f"Rs.{total_incentive:.2f}"],
            ["---", "---"],
            ["Month Running Sale", f"Rs.{total_month_net_amount:.2f}"],
            ["Month Running Incentive", f"Rs.{total_month_incentive:.2f}"],
        ]
        try:
            summary_table = Table(summary_data, colWidths=[100, 80])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e6f0fa')),
                ('BACKGROUND', (0, 3), (-1, -1), colors.HexColor('#e6f0fa')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.darkblue),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.grey),
                ('BACKGROUND', (0, 2), (-1, 2), colors.transparent),
                ('TEXTCOLOR', (0, 2), (-1, 2), colors.grey),
                ('FONTSIZE', (0, 2), (-1, 2), 8),
            ]))
            summary_table.wrapOn(c, width - 100, height)
            summary_height = summary_table._height
            if y_position - summary_height - 20 < 50:
                c.showPage()
                y_position = height - 70
                page_number += 1
            y_position -= summary_height + 20
            summary_table.drawOn(c, 50, y_position)
        except Exception as e:
            st.error(f"Error drawing summary table for {staff}: {e}")
            continue

        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.setLineWidth(0.5)
        c.line(50, 50, width - 50, 50)
        c.setFont("Helvetica", 10)
        c.drawString(50, 35, f"Page {page_number} of 1")
        c.drawRightString(width - 50, 35, "Generated by KNORKA 1.0")

        try:
            c.showPage()
            c.save()
            password = passwords.get(staff)
            if password:
                encrypt_pdf(temp_path, output_path, password)
                os.remove(temp_path)
            else:
                os.rename(temp_path, output_path)
        except Exception as e:
            st.error(f"Error saving PDF for {staff}: {e}")

# Original Detailed PDF (Restored)
def generate_detailed_pdf(selected_date=None, start_date=None, end_date=None):
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=letter)
    styles = getSampleStyleSheet()
    width, height = letter
    y_position = height - 70
    page_number = 1

    for staff in known_staff:
        if y_position < 150:
            c.showPage()
            page_number += 1
            y_position = height - 70

        if selected_date or not start_date:
            date_to_use = selected_date.strftime("%d-%m-%Y") if selected_date else report_date
            date_dt = datetime.strptime(date_to_use, "%d-%m-%Y")
            day_of_week = date_dt.strftime("%A").upper()
            header_date = date_to_use.replace('-', '/')
        else:
            date_dt = end_date
            day_of_week = date_dt.strftime("%A").upper()
            header_date = f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"

        c.setFont("Helvetica-Bold", 12)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        y_position -= 40
        c.drawString(50, y_position, f"Salesman Name: {staff.upper()}    Incentive Date: {header_date} - {day_of_week}")

        role = staff_list.get(staff, "Staff")
        if role == "Helper":
            cursor.execute("SELECT total_pool FROM incentives WHERE name = ? AND bill_no = 'Helper Pool' AND date = ?", (staff, date_to_use if not start_date else end_date.strftime("%d-%m-%Y")))
            total_pool_data = cursor.fetchone()
            total_pool = total_pool_data[0] if total_pool_data and total_pool_data[0] is not None else 0.0
            y_position -= 20
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(50, y_position, f"Total Helper Pool for the Day: Rs.{total_pool:.2f}")

        if not start_date:
            cursor.execute("SELECT bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool FROM incentives WHERE name = ? AND date = ?", (staff, date_to_use))
        else:
            cursor.execute("SELECT bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool FROM incentives WHERE name = ? AND date BETWEEN ? AND ?", (staff, start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
        bill_data = cursor.fetchall()

        table_headers = ["Bill No", "Item", "Qty", "Rate", "Amount", "Second Agent", "%", "Incentive"]
        table_data = [table_headers]
        total_net_amount = 0
        total_incentive = 0
        total_bills = set()

        for row in bill_data:
            bill_no, item_name, net_amount, incentive, date, name, qty, rate, second_agent, total_pool = row
            percent = (incentive / net_amount) * 100 if net_amount != 0 else 0
            rate_str = f"Rs.{rate:.2f}" if rate != 0 else "Rs.0.00"
            amount_str = f"Rs.{net_amount:.2f}" if net_amount != 0 else "Rs.0.00"
            incentive_str = f"Rs.{incentive:.2f}"
            second_agent_display = second_agent if second_agent else "N/A"
            table_data.append([bill_no, item_name, f"{qty:.1f}", rate_str, amount_str, second_agent_display, f"{percent:.3f}%", incentive_str])
            total_net_amount += net_amount
            total_incentive += incentive
            if bill_no != "Helper Pool":
                total_bills.add(bill_no)

        if len(table_data) > 1:
            table = Table(table_data, colWidths=[70, 100, 50, 60, 60, 80, 50, 60])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5f5f5')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            table.wrapOn(c, width - 100, height)
            table_height = table._height
            y_position -= table_height + 20
            table.drawOn(c, 50, y_position)

        month_start = date_dt.replace(day=1).strftime("%d-%m-%Y")
        cursor.execute("SELECT SUM(net_amount), SUM(incentive) FROM incentives WHERE name = ? AND date BETWEEN ? AND ?", (staff, month_start, date_to_use if not start_date else end_date.strftime("%d-%m-%Y")))
        month_totals = cursor.fetchone()
        total_month_net_amount = month_totals[0] if month_totals and month_totals[0] is not None else 0.0
        total_month_incentive = month_totals[1] if month_totals and month_totals[1] is not None else 0.0

        summary_data = [
            ["Sale (Current PDF)", f"Rs.{total_net_amount:.2f}"],
            ["Incentive (Current PDF)", f"Rs.{total_incentive:.2f}"],
            ["---", "---"],
            ["Month Running Sale", f"Rs.{total_month_net_amount:.2f}"],
            ["Month Running Incentive", f"Rs.{total_month_incentive:.2f}"],
        ]
        summary_table = Table(summary_data, colWidths=[100, 80])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e6f0fa')),
            ('BACKGROUND', (0, 3), (-1, -1), colors.HexColor('#e6f0fa')),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.darkblue),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.grey),
            ('BACKGROUND', (0, 2), (-1, 2), colors.transparent),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.grey),
            ('FONTSIZE', (0, 2), (-1, 2), 8),
        ]))
        summary_table.wrapOn(c, width - 100, height)
        summary_height = summary_table._height
        if y_position - summary_height - 20 < 50:
            c.showPage()
            y_position = height - 70
            page_number += 1
        y_position -= summary_height + 20
        summary_table.drawOn(c, 50, y_position)

        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.setLineWidth(0.5)
        c.line(50, 50, width - 50, 50)
        c.setFont("Helvetica", 10)
        c.drawString(50, 35, f"Page {page_number} of 1")
        c.drawRightString(width - 50, 35, "Generated by KNORKA 1.0")

    c.showPage()
    c.save()
    return output.getvalue()

# File Uploaders
st.subheader("Upload Files")
col1, col2 = st.columns(2)
with col1:
    erp_files = st.file_uploader("Upload Logic ERP Files (LS_Sales, NFS_Sales)", type=["xlsx"], accept_multiple_files=True, key="erp_files")
with col2:
    attendance_file = st.file_uploader("Upload Attendance File", type=["xlsx"], accept_multiple_files=False, key="attendance_file")

# Tabs
tab_names = ["Overview", "Search", "Reports", "Performance", "Detailed View", "Control Panel", "Attendance"]
tab = st.tabs(tab_names)

# Overview Tab (Fixed)
with tab[0]:
    st.markdown('<div class="header">Overview</div>', unsafe_allow_html=True)
    if erp_files and attendance_file and st.button("Process Files"):
        process_files(erp_files, attendance_file)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime(2025, 3, 1), key="overview_start")
    with col2:
        end_date = st.date_input("End Date", value=datetime.now(), key="overview_end")

    if start_date <= end_date:
        cursor.execute("SELECT SUM(incentive), SUM(gross) FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ?", (excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
        result = cursor.fetchone()
        total_incentive = float(result[0]) if result and result[0] is not None else 0.0
        total_gross = float(result[1]) if result and result[1] is not None else 0.0
        
        st.markdown('<div class="summary-card">', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Total Incentive:** {total_incentive:.2f}")
        with col2:
            st.markdown(f"**Total Gross:** {total_gross:.2f}")
        st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("Top Performers")
        col1, col2 = st.columns(2)
        with col1:
            cursor.execute("SELECT name, SUM(incentive) FROM incentives WHERE date = ? AND name NOT IN (?) GROUP BY name ORDER BY SUM(incentive) DESC LIMIT 1", (datetime.now().strftime("%d/%m/%Y"), excluded_names[0]))
            top_today = cursor.fetchone()
            st.markdown('<div class="top-salesman">', unsafe_allow_html=True)
            st.markdown("<h3>Today's Top Performer</h3>", unsafe_allow_html=True)
            if top_today and top_today[1] is not None:
                st.markdown(f"**{top_today[0]}**: {float(top_today[1]):.2f}")
            else:
                st.markdown("No data")
            st.markdown('</div>', unsafe_allow_html=True)
        with col2:
            cursor.execute("SELECT name, SUM(incentive) FROM incentives WHERE date BETWEEN ? AND ? AND name NOT IN (?) GROUP BY name ORDER BY SUM(incentive) DESC LIMIT 1", (start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y"), excluded_names[0]))
            top_range = cursor.fetchone()
            st.markdown('<div class="top-salesman">', unsafe_allow_html=True)
            st.markdown("<h3>Range's Top Performer</h3>", unsafe_allow_html=True)
            if top_range and top_range[1] is not None:
                st.markdown(f"**{top_range[0]}**: {float(top_range[1]):.2f}")
            else:
                st.markdown("No data")
            st.markdown('</div>', unsafe_allow_html=True)

# Search Tab
with tab[1]:
    st.markdown('<div class="header">Search Products</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime(2025, 3, 1), key="search_start")
    with col2:
        end_date = st.date_input("End Date", value=datetime.now(), key="search_end")

    if start_date <= end_date:
        search_type = st.selectbox("Search By", ["Item Name", "Item Code", "Additional Item Code"], key="search_type")
        search_term = st.text_input("Enter Search Term")
        if search_term:
            if search_type == "Item Name":
                cursor.execute("SELECT date, name, bill_no, item_name, net_amount, incentive FROM incentives WHERE item_name LIKE ? AND date BETWEEN ? AND ?", (f"%{search_term}%", start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            elif search_type == "Item Code":
                cursor.execute("SELECT date, name, bill_no, item_name, net_amount, incentive FROM incentives WHERE item_code LIKE ? AND date BETWEEN ? AND ?", (f"%{search_term}%", start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            else:  # Additional Item Code
                cursor.execute("SELECT date, name, bill_no, item_name, net_amount, incentive FROM incentives WHERE additional_item_code LIKE ? AND date BETWEEN ? AND ?", (f"%{search_term}%", start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            results = cursor.fetchall()
            if results:
                df = pd.DataFrame(results, columns=["Date", "Agent Name", "Bill No", "Item Name", "Net Amount", "Incentive"])
                st.dataframe(df)
            else:
                st.write("No matching results found.")

# Reports Tab
with tab[2]:
    st.markdown('<div class="header">Reports</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        show_preview = st.checkbox("Show Preview", key="show_preview")
    with col2:
        selected_date = st.date_input("Select Single Date", value=datetime.strptime(report_date, "%d-%m-%Y") if 'report_date' in globals() else datetime(2025, 3, 1), key="report_date")
    with col3:
        batch_mode = st.checkbox("Batch Mode", key="batch_mode")

    if batch_mode:
        with st.expander("Batch Date Range"):
            start_date = st.date_input("Start Date", value=datetime(2025, 3, 1), key="batch_start")
            end_date = st.date_input("End Date", value=datetime(2025, 3, 15), key="batch_end")
            if start_date <= end_date:
                if st.button("Generate PDFs for Range"):
                    cursor.execute("SELECT date FROM incentives WHERE date BETWEEN ? AND ?", (start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
                    if cursor.fetchone():
                        generate_pdfs_to_folder(start_date=start_date, end_date=end_date)
                        st.success(f"PDFs generated for {start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}")
                    else:
                        st.warning("No data for this range")
                if st.button("Download Detailed PDF for Range"):
                    pdf_data = generate_detailed_pdf(start_date=start_date, end_date=end_date)
                    st.download_button("Download PDF", pdf_data, file_name=f"overview_{start_date.strftime('%d-%m-%Y')}_to_{end_date.strftime('%d-%m-%Y')}.pdf", mime="application/pdf")
    else:
        if st.button("Generate PDFs for Date"):
            cursor.execute("SELECT date FROM incentives WHERE date = ?", (selected_date.strftime("%d-%m-%Y"),))
            if cursor.fetchone():
                generate_pdfs_to_folder(selected_date=selected_date)
                st.success(f"PDFs generated for {selected_date.strftime('%d/%m/%Y')}")
            else:
                st.warning("No data for this date")
        if st.button("Download Detailed PDF for Date"):
            pdf_data = generate_detailed_pdf(selected_date=selected_date)
            st.download_button("Download PDF", pdf_data, file_name=f"overview_{selected_date.strftime('%d-%m-%Y')}.pdf", mime="application/pdf")

    if st.button("Create Backup of PDFs"):
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs_backup")
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs")):
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            backup_path = os.path.join(backup_dir, f"pdfs_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs")):
                    for file in files:
                        zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs")))
            st.success(f"Backup created at {backup_path}")
        else:
            st.warning("No PDFs folder found")

    if st.button("Compress PDFs Older Than"):
        days_old = st.number_input("Days", min_value=1, value=30, key="compress_days")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pdfs_dir = os.path.join(base_dir, "pdfs")
        if os.path.exists(pdfs_dir):
            archive_dir = os.path.join(base_dir, "pdfs_archive")
            if not os.path.exists(archive_dir):
                os.makedirs(archive_dir)
            archive_path = os.path.join(archive_dir, f"pdfs_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(pdfs_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if os.path.getmtime(file_path) < (datetime.now() - timedelta(days=days_old)).timestamp():
                            zipf.write(file_path, os.path.relpath(file_path, pdfs_dir))
                            os.remove(file_path)
            st.success(f"Compressed PDFs older than {days_old} days to {archive_path}")
        else:
            st.warning("No PDFs folder found")

# Performance Tab
with tab[3]:
    st.markdown('<div class="header">Performance</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime(2025, 3, 1), key="perf_start")
    with col2:
        end_date = st.date_input("End Date", value=datetime.now(), key="perf_end")

    if start_date <= end_date:
        role_filter = st.selectbox("Filter by Role", ["All", "Salesman", "Helper", "Stockboy", "General"], key="perf_role")
        filtered_staff = known_staff if role_filter == "All" else [s for s in known_staff if staff_list[s] == role_filter]

        cursor.execute("SELECT name, SUM(incentive) FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ? GROUP BY name ORDER BY SUM(incentive) DESC LIMIT 1", (excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
        top_performer = cursor.fetchone()
        top_performer_name = top_performer[0] if top_performer else None

        staff_data = []
        for i in range(0, len(filtered_staff), 3):
            cols = st.columns(3)
            for j, staff in enumerate(filtered_staff[i:i+3]):
                cursor.execute("SELECT SUM(incentive), SUM(gross) FROM incentives WHERE name = ? AND date = ? AND bill_no != 'Helper Pool'", (staff, datetime.now().strftime("%d/%m/%Y")))
                today_result = cursor.fetchone()
                today_incentive = float(today_result[0]) if today_result and today_result[0] is not None else 0.0
                today_gross = float(today_result[1]) if today_result and today_result[1] is not None else 0.0
                
                cursor.execute("SELECT SUM(incentive), SUM(gross) FROM incentives WHERE name = ? AND date BETWEEN ? AND ? AND bill_no != 'Helper Pool'", (staff, start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
                range_result = cursor.fetchone()
                range_incentive = float(range_result[0]) if range_result and range_result[0] is not None else 0.0
                range_gross = float(range_result[1]) if range_result and range_result[1] is not None else 0.0
                
                with cols[j]:
                    st.markdown('<div class="staff-box">', unsafe_allow_html=True)
                    star = " ★" if staff == top_performer_name else ""
                    st.markdown(f"<h3>{staff}{star}</h3>", unsafe_allow_html=True)
                    st.markdown(f"**Today's Sale:** {today_gross:.2f}")
                    st.markdown(f"**Today's Incentive:** {today_incentive:.2f}")
                    st.markdown(f"**Range Sale:** {range_gross:.2f}")
                    st.markdown(f"**Range Incentive:** {range_incentive:.2f}")
                    st.markdown('</div>', unsafe_allow_html=True)
                staff_data.append([staff, today_gross, today_incentive, range_gross, range_incentive])

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Export Staff Overview as Excel"):
                df = pd.DataFrame(staff_data, columns=["Name", "Today's Sale", "Today's Incentive", "Range Sale", "Range Incentive"])
                output = BytesIO()
                df.to_excel(output, index=False)
                st.download_button("Download Excel", output.getvalue(), file_name="staff_overview.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col2:
            if st.button("Export Staff Overview as PDF"):
                pdf_data = generate_detailed_pdf(start_date=start_date, end_date=end_date)
                st.download_button("Download PDF", pdf_data, file_name=f"staff_overview_{start_date.strftime('%d-%m-%Y')}_to_{end_date.strftime('%d-%m-%Y')}.pdf", mime="application/pdf")

        st.subheader("Charts")
        chart_type = st.selectbox("Select Chart Type", ["Pie", "Bar", "Line"], key="chart_type")
        if chart_type == "Pie":
            cursor.execute("SELECT name, SUM(incentive) FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ? GROUP BY name", (excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            chart_data = cursor.fetchall()
            if chart_data:
                df = pd.DataFrame(chart_data, columns=["Name", "Incentive"])
                fig = px.pie(df, names="Name", values="Incentive", title="Incentive Distribution")
                st.plotly_chart(fig, use_container_width=True)
        elif chart_type == "Bar":
            cursor.execute("SELECT date, SUM(gross) FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ? GROUP BY date ORDER BY date", (excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            chart_data = cursor.fetchall()
            if chart_data:
                df = pd.DataFrame(chart_data, columns=["Date", "Gross"])
                fig = px.bar(df, x="Date", y="Gross", title="Sales Trend")
                st.plotly_chart(fig, use_container_width=True)
        elif chart_type == "Line":
            cursor.execute("SELECT strftime('%m', date) as month, SUM(incentive) FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ? GROUP BY month ORDER BY month", (excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")))
            chart_data = cursor.fetchall()
            if chart_data:
                df = pd.DataFrame(chart_data, columns=["Month", "Incentive"])
                fig = px.line(df, x="Month", y="Incentive", title="Monthly Incentive Trend")
                st.plotly_chart(fig, use_container_width=True)

        if st.button("Refresh"):
            st.experimental_rerun()

# Detailed View Tab
with tab[4]:
    st.markdown('<div class="header">Detailed View</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime(2025, 3, 1), key="detail_start")
    with col2:
        end_date = st.date_input("End Date", value=datetime(2025, 3, 15), key="detail_end")
    staff = st.selectbox("Select Staff", ["All"] + known_staff, key="detail_staff")
    
    if st.button("Generate Report"):
        query = "SELECT * FROM incentives WHERE name NOT IN (?) AND date BETWEEN ? AND ?"
        params = [excluded_names[0], start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y")]
        if staff != "All":
            query += " AND name = ?"
            params.append(staff)
        cursor.execute(query, params)
        detailed_data = cursor.fetchall()
        if detailed_data:
            df = pd.DataFrame(detailed_data, columns=["Date", "Name", "Role", "Incentive", "Gross", "Net Amount", "Status", "Bill No", "Item Name", "Company", "Qty", "Rate", "Second Agent", "Parts Count", "Total Pool", "Item Code", "Additional Item Code"])
            st.dataframe(df)
        else:
            st.write("No data found.")

# Control Panel Tab
with tab[5]:
    st.markdown('<div class="header">Control Panel</div>', unsafe_allow_html=True)
    st.subheader("Edit Staff")
    new_staff = st.text_input("Add New Staff")
    if st.button("Add Staff"):
        if new_staff and new_staff not in known_staff:
            staff_list[new_staff] = "Salesman"
            known_staff.append(new_staff)
            st.success(f"Added {new_staff}")
            logging.info(f"Added staff: {new_staff}")

    st.subheader("Edit Role")
    staff_to_edit = st.selectbox("Select Staff", [""] + known_staff, key="edit_role")
    if staff_to_edit:
        current_role = staff_list.get(staff_to_edit, "Staff")
        new_role = st.selectbox("New Role", ["Salesman", "Helper", "Stockboy", "General"], index=["Salesman", "Helper", "Stockboy", "General"].index(current_role))
        if st.button("Update Role"):
            staff_list[staff_to_edit] = new_role
            cursor.execute("UPDATE incentives SET role = ? WHERE name = ?", (new_role, staff_to_edit))
            conn.commit()
            st.success(f"Updated {staff_to_edit} to {new_role}")

    st.subheader("Edit Incentive")
    staff = st.selectbox("Select Staff", [""] + known_staff, key="edit_incentive")
    if staff:
        cursor.execute("SELECT incentive FROM incentives WHERE name = ? AND date = ?", (staff, "12/03/2025"))
        current_incentive = cursor.fetchone()
        new_incentive = st.number_input("New Incentive", value=current_incentive[0] if current_incentive else 0.0)
        if st.button("Update Incentive"):
            cursor.execute("UPDATE incentives SET incentive = ? WHERE name = ? AND date = ?", (new_incentive, staff, "12/03/2025"))
            conn.commit()
            st.success(f"Updated incentive for {staff} to {new_incentive}")

    st.subheader("Record Payment")
    staff_payment = st.selectbox("Select Staff", [""] + known_staff, key="payment_staff")
    payment_amount = st.number_input("Payment Amount", value=0.0)
    payment_date = st.date_input("Payment Date", value=datetime.now())
    if st.button("Record Payment"):
        if staff_payment:
            cursor.execute("INSERT INTO payments VALUES (?, ?, ?, ?)", (datetime.now().strftime("%d/%m/%Y"), staff_payment, payment_amount, payment_date.strftime("%d/%m/%Y")))
            conn.commit()
            st.success(f"Recorded Rs.{payment_amount:.2f} for {staff_payment} on {payment_date.strftime('%d/%m/%Y')}")

    st.subheader("Adjust Incentive")
    staff_adjust = st.selectbox("Select Staff", [""] + known_staff, key="adjust_staff")
    adjustment_type = st.selectbox("Type", ["Extra Incentive", "Cut Incentive"])
    adjustment_value = st.number_input("Value", value=0.0)
    adjustment_percent = st.number_input("Percentage (%)", value=0.0)
    if st.button("Apply Adjustment"):
        if staff_adjust:
            cursor.execute("SELECT incentive, gross FROM incentives WHERE name = ? AND date = ?", (staff_adjust, "12/03/2025"))
            data = cursor.fetchone()
            if data:
                incentive, gross = data
                if adjustment_type == "Extra Incentive":
                    new_incentive = incentive + (adjustment_value + (gross * adjustment_percent / 100))
                else:
                    new_incentive = incentive - (adjustment_value + (gross * adjustment_percent / 100))
                cursor.execute("UPDATE incentives SET incentive = ? WHERE name = ? AND date = ?", (new_incentive, staff_adjust, "12/03/2025"))
                conn.commit()
                st.success(f"Adjusted incentive for {staff_adjust} to {new_incentive}")

# Attendance Tab
with tab[6]:
    st.markdown('<div class="header">Attendance</div>', unsafe_allow_html=True)
    if attendance_file:
        attendance = pd.read_excel(attendance_file, skiprows=6)
        attendance.columns = attendance.columns.str.strip()
        present = len(attendance[attendance["Status"].isin(["P", "A"])])
        absent = len(attendance) - present
        st.metric("Total Present", present)
        st.metric("Total Absent", absent)
    else:
        st.warning("Please upload an attendance file.")

conn.close()
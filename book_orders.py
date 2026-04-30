import json
import os
import re
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

AIRTABLE_API_KEY = os.environ['AIRTABLE_API_KEY']
AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
SHOPIFY_STORE_URL = os.environ['SHOPIFY_STORE_URL']
SHOPIFY_API_TOKEN = os.environ['SHOPIFY_API_TOKEN']
SHOPIFY_API_VERSION = '2024-01'
BOOK_ORDER_TABLES = os.environ['BOOK_ORDER_TABLES']
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_BOOKS = os.environ.get('SMTP_FROM_BOOKS', '') or os.environ.get('SMTP_USER', '')
ERROR_EMAIL_TO = os.environ.get('ERROR_EMAIL_TO', '')

# Per-table override of which column to use as the invoice number in the email subject.
# Format: JSON object e.g. {"Table A": "PO#", "Table B": "CW Receipt"}
# Tables not listed default to "Invoice #".
_raw = os.environ.get('BOOK_ORDER_INVOICE_FIELDS', '{}')
INVOICE_FIELD_BY_TABLE = json.loads(_raw)

TRIGGER_STATUS = '📚 Submit Book Order'
DEFAULT_INVOICE_FIELD = 'Invoice #'
ORDER_FIELDS = [
    'Parent Name', 'Parent Email', 'Phone',
    'Address Line 1', 'Address Line 2', 'City', 'State', 'Zip Code',
    'Quantity', 'Workbooks Ordered', 'Shopify Order ID', 'Automation Log',
    'Invoice #', 'PO#', 'CW Receipt',
]


# ── Airtable helpers (table-parameterized) ───────────────────────────────────

def get_records(table_name, filter_formula, fields=None):
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{requests.utils.quote(table_name, safe="")}'
    params = {'filterByFormula': filter_formula, 'pageSize': 100}
    if fields:
        params['fields[]'] = fields
    records = []
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset
    return records


def update_record(table_name, record_id, fields):
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json',
    }
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{requests.utils.quote(table_name, safe="")}/{record_id}'
    r = requests.patch(url, headers=headers, json={'fields': fields}, timeout=30)
    r.raise_for_status()


# ── Email ─────────────────────────────────────────────────────────────────────

def send_error_email(subject, body):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ERROR_EMAIL_TO]):
        print(f'Error email not configured. Error was: {subject}')
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM_BOOKS
        msg['To'] = ERROR_EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f'Error email sent to {ERROR_EMAIL_TO}')
    except Exception as e:
        print(f'Failed to send error email: {e}')


def send_order_confirmation_email(to_email, order_number, workbook_items, recipient_name,
                                   address_line1, address_line2, city, state, zip_code, phone):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        print(f'Email not configured — skipping confirmation email for order {order_number}')
        return
    try:
        address_parts = [address_line1]
        if address_line2:
            address_parts.append(address_line2)
        address_parts.append(f'{city}, {state} {zip_code}'.strip())
        mailing_address = ', '.join(p for p in address_parts if p)

        order_items_html = '\n'.join(
            f'<li><strong>{name}</strong> (Quantity = {qty})</li>'
            for name, qty in workbook_items
        )

        html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 15px; color: #222; max-width: 650px;">
            <p>Hi,</p>

            <p>We are happy to inform you that your workbook purchase order has been successfully processed.
            Thank you for your purchase!</p>

            <p>Below are the order details for your reference:</p>

            <ul style="line-height: 2;">
                {order_items_html}
            </ul>

            <ul style="line-height: 2;">
                <li>Recipient full name: <strong>{recipient_name}</strong></li>
                <li>Recipient mailing address: <strong>{mailing_address}</strong></li>
                <li>Recipient phone number: <strong>{phone}</strong></li>
            </ul>

            <p>Once your workbooks are on the way, the tracking number will be emailed to you.
            Please allow 7-9 business days for delivery.</p>

            <p>We sincerely appreciate your patience and support. Have a great day!</p>

            <p>Warm Regards,<br><strong>Miaplaza Workbooks Team</strong></p>
        </div>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Your Workbook Order ({order_number}) Has Been Processed'
        msg['From'] = f'Miaplaza Workbooks <{SMTP_FROM_BOOKS}>'
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f'Confirmation email sent to {to_email} for order {order_number}')
    except Exception as e:
        print(f'Failed to send confirmation email for order {order_number}: {e}')


# ── Shopify helpers ───────────────────────────────────────────────────────────

def get_shopify_barcode_map():
    """Fetch all product variants and return {barcode.lower(): variant_id}."""
    headers = {'X-Shopify-Access-Token': SHOPIFY_API_TOKEN}
    url = f'https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/products.json?limit=250&fields=id,variants'
    barcode_map = {}
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        for product in r.json().get('products', []):
            for variant in product.get('variants', []):
                if variant.get('barcode'):
                    barcode_map[variant['barcode'].lower()] = variant['id']
        link = r.headers.get('Link', '')
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match.group(1) if match else None
    return barcode_map


def get_workbook_map():
    """Return {airtable_record_id: {'barcode': str, 'name': str}} from Workbooks table."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Workbooks'
    params = {'fields[]': ['Name', 'Barcode'], 'pageSize': 100}
    workbook_map = {}
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        for record in data.get('records', []):
            f = record.get('fields', {})
            workbook_map[record['id']] = {
                'barcode': (f.get('Barcode') or '').lower(),
                'name': f.get('Name', ''),
            }
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset
    return workbook_map


def create_shopify_order(line_items, shipping_address, email):
    """Returns (order_id, order_number)."""
    headers = {
        'X-Shopify-Access-Token': SHOPIFY_API_TOKEN,
        'Content-Type': 'application/json',
    }
    url = f'https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/orders.json'
    body = {
        'order': {
            'email': email,
            'financial_status': 'paid',
            'send_receipt': False,
            'send_fulfillment_receipt': False,
            'line_items': line_items,
            'shipping_address': shipping_address,
            'shipping_lines': [
                {'title': 'Express (2 to 5 business days)', 'price': '0.00', 'code': 'Express'},
            ],
        }
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    print(f'Shopify response {r.status_code}: {r.text[:300]}')
    r.raise_for_status()
    order = r.json()['order']
    return str(order['id']), str(order['order_number'])


# ── Per-table processing ──────────────────────────────────────────────────────

def process_table(table_name, barcode_map, workbook_map):
    formula = f"AND({{Status}} = '{TRIGGER_STATUS}', NOT({{Shopify Order ID}}))"
    records = get_records(table_name, formula)
    print(f'  {table_name}: {len(records)} pending order(s)')

    for record in records:
        f = record.get('fields', {})
        record_id = record['id']
        log = []

        linked = f.get('Workbooks Ordered') or []
        quantity = int(f.get('Quantity') or 1)

        line_items = []
        workbook_items = []  # (name, quantity) for confirmation email
        for wb_id in linked:
            wb = workbook_map.get(wb_id, {})
            barcode = wb.get('barcode', '')
            name = wb.get('name', '')
            variant_id = barcode_map.get(barcode)
            if not variant_id:
                msg = f'ERROR: barcode "{barcode}" ({name}) not found in Shopify'
                log.append(msg)
                print(f'  {msg} — skipping record {record_id}')
                line_items = []
                break
            line_items.append({'variant_id': variant_id, 'quantity': quantity})
            workbook_items.append((name, quantity))

        if not line_items:
            if log:
                update_record(table_name, record_id, {'Automation Log': ' | '.join(log)})
                send_error_email(
                    f'Book Order Error: {table_name} / {record_id}',
                    f'Could not create Shopify order for record {record_id} in "{table_name}".\n\nLog: {" | ".join(log)}',
                )
            continue

        full_name = (f.get('Parent Name') or '').strip()
        first, *rest = full_name.split(' ', 1)
        shipping_address = {
            'first_name': first,
            'last_name': rest[0] if rest else '',
            'phone': f.get('Phone', ''),
            'address1': f.get('Address Line 1', ''),
            'address2': f.get('Address Line 2', ''),
            'city': f.get('City', ''),
            'province_code': f.get('State', ''),
            'country_code': 'US',
            'zip': f.get('Zip Code', ''),
        }

        try:
            order_id, order_number = create_shopify_order(line_items, shipping_address, f.get('Parent Email', ''))
            invoice_field = INVOICE_FIELD_BY_TABLE.get(table_name, DEFAULT_INVOICE_FIELD)
            invoice_number = f.get(invoice_field) or order_number
            log.append(f'Shopify order #{order_number} created ({len(line_items)} item(s), qty {quantity})')
            update_record(table_name, record_id, {
                'Shopify Order ID': order_id,
                'Automation Log': ' | '.join(log),
            })
            print(f'  Created Shopify order #{order_number} for {full_name}')
            send_order_confirmation_email(
                to_email=f.get('Parent Email', ''),
                order_number=invoice_number,
                workbook_items=workbook_items,
                recipient_name=full_name,
                address_line1=f.get('Address Line 1', ''),
                address_line2=f.get('Address Line 2', ''),
                city=f.get('City', ''),
                state=f.get('State', ''),
                zip_code=f.get('Zip Code', ''),
                phone=f.get('Phone', ''),
            )
        except Exception as e:
            log.append(f'ERROR creating Shopify order: {e}')
            update_record(table_name, record_id, {'Automation Log': ' | '.join(log)})
            print(f'  ERROR creating order for {full_name} in {table_name}: {e}')
            send_error_email(
                f'Book Order Error: {full_name} / {table_name}',
                f'Failed to create Shopify order for {full_name} in "{table_name}".\n\nLog: {" | ".join(log)}\n\nError: {e}',
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    tables = [t.strip() for t in BOOK_ORDER_TABLES.split(',') if t.strip()]
    print(f'Processing {len(tables)} table(s) for book orders...')

    barcode_map = get_shopify_barcode_map()
    print(f'Loaded {len(barcode_map)} Shopify variant barcodes')

    workbook_map = get_workbook_map()
    print(f'Loaded {len(workbook_map)} Workbook records')

    for table_name in tables:
        process_table(table_name, barcode_map, workbook_map)


if __name__ == '__main__':
    main()

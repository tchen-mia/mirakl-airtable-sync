import os
import requests
import smtplib
from datetime import date, timedelta
from email.mime.text import MIMEText

MIRAKL_API_URL = os.environ['MIRAKL_API_URL']
MIRAKL_API_KEY = os.environ['MIRAKL_API_KEY']
AIRTABLE_API_KEY = os.environ['AIRTABLE_API_KEY']
AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
AIRTABLE_TABLE_NAME = os.environ['AIRTABLE_TABLE_NAME']
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
ERROR_EMAIL_TO = os.environ.get('ERROR_EMAIL_TO', '')

# Maps each SKU to its Type, Site, and how many months one unit represents.
# 'duration' is used for fixed durations (e.g. lifetime) instead of calculating from quantity.
SKU_MAP = {
    'MIA1MO':   {'type': 'Monthly', 'site': 'MIA', 'months_per_unit': 1},
    'MIA12MO':  {'type': 'Annual',  'site': 'MIA', 'months_per_unit': 12},
    'MIALIFE':  {'type': 'IndLife', 'site': 'MIA', 'duration': 'lifetime'},
    'MP1MO':    {'type': 'Monthly', 'site': 'MP',  'months_per_unit': 1},
    'MP12MO':   {'type': 'Annual',  'site': 'MP',  'months_per_unit': 12},
    'MPLIFE':   {'type': 'IndLife', 'site': 'MP',  'duration': 'lifetime'},
    'MPPMP1MO': {'type': 'Monthly', 'site': 'MP+', 'months_per_unit': 1},
    'MPP1MO':   {'type': 'Monthly', 'site': 'MP+', 'months_per_unit': 1},
}

# All valid Duration options in Airtable
VALID_DURATIONS = {
    '1-month', '2-month', '3-month', '4-month', '5-month',
    '6-month', '7-month', '8-month', '9-month', '10-month',
    '11-month', '12-month', '24-month', '36-month', 'lifetime'
}


def send_error_email(subject, body):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ERROR_EMAIL_TO]):
        print(f"Email not configured. Error was: {subject}")
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = ERROR_EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Error email sent to {ERROR_EMAIL_TO}")
    except Exception as e:
        print(f"Failed to send error email: {e}")


def get_mirakl_orders():
    """Fetch all orders with status Pending Acceptance from Mirakl."""
    headers = {'Authorization': MIRAKL_API_KEY}
    params = {'order_state_codes': 'WAITING_ACCEPTANCE', 'max': 100}
    response = requests.get(
        f"{MIRAKL_API_URL}/api/orders",
        headers=headers,
        params=params,
        timeout=30
    )
    response.raise_for_status()
    return response.json().get('orders', [])


def get_existing_order_ids():
    """Return the set of order IDs already in Airtable to prevent duplicates."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    existing = set()
    params = {'fields[]': 'Ariba Invoice #', 'pageSize': 100}

    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        for record in data.get('records', []):
            order_id = record.get('fields', {}).get('Ariba Invoice #')
            if order_id:
                existing.add(order_id)
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset

    return existing


def map_sku(sku, quantity):
    """
    Return (type, duration, site, needs_review) for a given SKU and quantity.
    needs_review=True flags rows the script couldn't fully map.
    """
    if sku.startswith('BOOK'):
        return ('Book', None, None, False)

    if sku not in SKU_MAP:
        return (None, None, None, True)

    info = SKU_MAP[sku]
    sku_type = info['type']
    site = info['site']

    if 'duration' in info:
        return (sku_type, info['duration'], site, False)

    total_months = info['months_per_unit'] * quantity
    candidate = f"{total_months}-month"
    if candidate in VALID_DURATIONS:
        return (sku_type, candidate, site, False)

    # Duration exists but not in the Airtable dropdown (e.g. 13-month)
    return (sku_type, None, site, True)


def get_workbook_map():
    """Return a dict mapping workbook name (lowercase) → Airtable record ID."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Workbooks"
    workbook_map = {}
    params = {'fields[]': 'Name', 'pageSize': 100}
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        for record in data.get('records', []):
            name = record.get('fields', {}).get('Name', '')
            if name:
                workbook_map[name.lower()] = record['id']
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset
    return workbook_map


def create_airtable_record(fields):
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    response = requests.post(url, headers=headers, json={'fields': fields}, timeout=30)
    if not response.ok:
        print(f"Airtable error {response.status_code}: {response.text}")
        print(f"Fields sent: {fields}")
    response.raise_for_status()


def sync_orders():
    try:
        existing_ids = get_existing_order_ids()
        orders = get_mirakl_orders()
        workbook_map = get_workbook_map()
        new_count = 0

        for order in orders:
            order_id = order.get('order_id')
            if order_id in existing_ids:
                continue

            # Parse order date (Mirakl returns ISO 8601, Airtable expects YYYY-MM-DD)
            created_date = order.get('created_date', '')[:10]

            customer = order.get('customer', {})
            customer_name = f"{customer.get('firstname', '')} {customer.get('lastname', '')}".strip()
            customer_email = customer.get('email', '')

            # Shipping address (available at WAITING_ACCEPTANCE)
            addr = customer.get('shipping_address', {})
            address_fields = {}
            if addr.get('street1'):
                address_fields['Address Line 1'] = addr['street1']
            if addr.get('street2'):
                address_fields['Address Line 2'] = addr['street2']
            if addr.get('city'):
                address_fields['City'] = addr['city']
            if addr.get('state_code'):
                address_fields['State'] = addr['state_code']
            if addr.get('zip_code'):
                address_fields['Zip Code'] = addr['zip_code']
            phone = addr.get('phone') or addr.get('phone_secondary') or customer.get('phone', '')
            if phone:
                address_fields['Phone'] = phone

            # Merge line items with the same SKU (each order is for one student,
            # so duplicate SKUs mean multiple months/units of the same product)
            merged = {}
            for line in order.get('order_lines', []):
                sku = line.get('offer_sku', '')
                quantity = int(line.get('quantity', 1))
                amount = float(line.get('total_price', line.get('price', 0)))
                title = line.get('product_title', '')
                if sku in merged:
                    merged[sku]['quantity'] += quantity
                    merged[sku]['amount'] += amount
                else:
                    merged[sku] = {'quantity': quantity, 'amount': amount, 'title': title}

            for sku, data in merged.items():
                quantity = data['quantity']
                amount = data['amount']
                title = data.get('title', '')

                sku_type, duration, site, needs_review = map_sku(sku, quantity)
                mirakl_status = 'New - Review' if needs_review else 'New'

                fields = {
                    'Ariba Invoice #': order_id,
                    'Date': created_date,
                    'Amount': amount,
                    'Child Name': customer_name,
                    'Parent Email': customer_email,
                    'Mirakl': mirakl_status,
                    **address_fields,
                }
                if sku_type:
                    fields['Type'] = [sku_type]  # Multi-select requires a list
                if duration:
                    fields['Duration'] = duration
                if site:
                    fields['Site'] = site
                if title:
                    workbook_id = workbook_map.get(title.lower())
                    if workbook_id:
                        fields['Workbooks'] = [workbook_id]
                    else:
                        print(f"No Workbooks match found for: {title!r}")
                        fields['Mirakl'] = 'New - Review'

                create_airtable_record(fields)
                new_count += 1

        print(f"Done. {new_count} new line item(s) added to Airtable.")

        # Alert on orders approaching the 5-day auto-cancel deadline
        alert_threshold = str(date.today() - timedelta(days=3))
        at_risk = [o for o in orders if o.get('created_date', '')[:10] <= alert_threshold]
        if at_risk:
            ids = '\n'.join(o.get('order_id', '') for o in at_risk)
            send_error_email(
                "Mirakl Orders Approaching Auto-Cancel Deadline",
                f"The following orders have been in WAITING_ACCEPTANCE for 3+ days "
                f"and will auto-cancel after 5 days if not confirmed:\n\n{ids}\n\n"
                f"Please confirm or reject them as soon as possible."
            )

    except Exception as e:
        msg = f"sync_orders.py failed: {e}"
        print(msg)
        send_error_email("Mirakl Sync Error", msg)
        raise


if __name__ == '__main__':
    sync_orders()

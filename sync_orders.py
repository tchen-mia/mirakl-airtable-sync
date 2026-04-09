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
    'MIA1MO':   {'type': 'Monthly',      'site': 'MIA', 'months_per_unit': 1},
    'MIA12MO':  {'type': 'Annual',       'site': 'MIA', 'months_per_unit': 12},
    'MIALIFE':  {'type': 'IndLife',      'site': 'MIA', 'duration': 'lifetime'},
    'MP1MO':    {'type': 'Monthly',      'site': 'MP',  'months_per_unit': 1},
    'MP12MO':   {'type': 'Annual',       'site': 'MP',  'months_per_unit': 12},
    'MPLIFE':   {'type': 'IndLife',      'site': 'MP',  'duration': 'lifetime'},
    'MPPMP1MO': {'type': 'Monthly',      'site': 'MP+', 'months_per_unit': 1},
    'MPP1MO':   {'type': 'Monthly',      'site': 'MP+', 'months_per_unit': 1},
    'ST12MO':   {'type': 'SuperTeacher', 'site': None,  'months_per_unit': 12},
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
        for record in data.get('records') or []:
            order_id = (record.get('fields') or {}).get('Ariba Invoice #')
            if order_id:
                existing.add(order_id)
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset

    return existing


def map_sku(sku, quantity):
    """
    Return (type, duration, site, needs_review, review_reason) for a given SKU and quantity.
    needs_review=True flags rows the script couldn't fully map.
    """
    if sku.startswith('BOOK'):
        return ('Book', None, None, False, None)

    if sku not in SKU_MAP:
        return (None, None, None, True, f'Unknown SKU: {sku}')

    info = SKU_MAP[sku]
    sku_type = info['type']
    site = info['site']

    if 'duration' in info:
        return (sku_type, info['duration'], site, False, None)

    total_months = info['months_per_unit'] * quantity
    candidate = f"{total_months}-month"
    if candidate in VALID_DURATIONS:
        return (sku_type, candidate, site, False, None)

    # Duration exists but not in the Airtable dropdown (e.g. 13-month)
    return (sku_type, None, site, True, f'Duration {total_months}-month not in Airtable dropdown')


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
        for record in data.get('records') or []:
            name = (record.get('fields') or {}).get('Name', '')
            if name:
                workbook_map[name.lower()] = record['id']
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset
    return workbook_map


def create_airtable_record(fields):
    """Create an Airtable record and return its record ID."""
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
    return response.json()['id']


def update_airtable_record(record_id, fields):
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    response = requests.patch(url, headers=headers, json={'fields': fields}, timeout=30)
    response.raise_for_status()


def get_order_line_ids(order_id):
    """Fetch order from Mirakl and return its line IDs."""
    headers = {'Authorization': MIRAKL_API_KEY}
    response = requests.get(
        f"{MIRAKL_API_URL}/api/orders",
        headers=headers,
        params={'order_ids': order_id},
        timeout=30
    )
    response.raise_for_status()
    orders = response.json().get('orders', [])
    if not orders:
        raise Exception(f"Order {order_id} not found in Mirakl")
    return [line['order_line_id'] for line in orders[0].get('order_lines', [])]


def accept_order_in_mirakl(order_id):
    """Accept all order lines via Mirakl OR21."""
    line_ids = get_order_line_ids(order_id)
    if not line_ids:
        raise Exception(f"No order lines found for order {order_id}")
    headers = {
        'Authorization': MIRAKL_API_KEY,
        'Content-Type': 'application/json'
    }
    body = {
        'order_lines': [
            {'id': line_id, 'accepted': True}
            for line_id in line_ids
        ]
    }
    response = requests.put(
        f"{MIRAKL_API_URL}/api/orders/{order_id}/accept",
        headers=headers,
        json=body,
        timeout=30
    )
    if not response.ok:
        print(f"Mirakl accept error {response.status_code}: {response.text}")
    response.raise_for_status()


def sync_orders():
    try:
        existing_ids = get_existing_order_ids()
        orders = get_mirakl_orders()
        workbook_map = get_workbook_map()
        new_count = 0
        auto_confirmed_ids = set()

        for order in orders:
            order_id = order.get('order_id')
            if order_id in existing_ids:
                continue

            # Parse order date (Mirakl returns ISO 8601, Airtable expects YYYY-MM-DD)
            created_date = (order.get('created_date') or '')[:10]

            customer = order.get('customer') or {}
            customer_name = f"{customer.get('firstname', '')} {customer.get('lastname', '')}".strip()
            customer_email = customer.get('email', '')

            # Shipping address (available at WAITING_ACCEPTANCE)
            addr = customer.get('shipping_address') or {}
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
            for line in order.get('order_lines') or []:
                sku = line.get('offer_sku') or ''
                quantity = int(line.get('quantity') or 1)
                amount = float(line.get('total_price') or line.get('price') or 0)
                title = line.get('product_title') or ''
                if sku in merged:
                    merged[sku]['quantity'] += quantity
                    merged[sku]['amount'] += amount
                else:
                    merged[sku] = {'quantity': quantity, 'amount': amount, 'title': title}

            # First pass: determine if any line item needs review before creating records
            any_needs_review = False
            processed_items = []
            for sku, data in merged.items():
                quantity = data['quantity']
                amount = data['amount']
                title = data.get('title', '')

                sku_type, duration, site, needs_review, review_reason = map_sku(sku, quantity)

                # Only match workbooks for Book-type items
                workbook_id = None
                if sku_type == 'Book':
                    workbook_id = workbook_map.get(title.lower()) if title else None
                    if not workbook_id:
                        print(f"Order {order_id}: no Workbooks match for book {title!r}")
                        needs_review = True
                        review_reason = f"Workbook not matched: '{title}'"

                if needs_review:
                    any_needs_review = True

                processed_items.append({
                    'sku': sku,
                    'quantity': quantity,
                    'amount': amount,
                    'sku_type': sku_type,
                    'duration': duration,
                    'site': site,
                    'needs_review': needs_review,
                    'review_reason': review_reason,
                    'workbook_id': workbook_id,
                })

            # Second pass: create Airtable records
            created_record_ids = []
            for item in processed_items:
                mirakl_status = 'New - Review' if item['needs_review'] else 'New'
                fields = {
                    'Ariba Invoice #': order_id,
                    'Date': created_date,
                    'Amount': item['amount'],
                    'Child Name': customer_name,
                    'Parent Email': customer_email,
                    'Mirakl': mirakl_status,
                    **address_fields,
                }
                if item['sku_type']:
                    fields['Type'] = [item['sku_type']]
                if item['duration']:
                    fields['Duration'] = item['duration']
                if item['site']:
                    fields['Site'] = item['site']
                if item['workbook_id']:
                    fields['Workbooks'] = [item['workbook_id']]
                fields['Quantity'] = item['quantity']
                if item.get('review_reason'):
                    fields['Automation Log'] = item['review_reason']

                record_id = create_airtable_record(fields)
                created_record_ids.append(record_id)
                new_count += 1

            # Auto-accept in Mirakl if all line items mapped cleanly
            if not any_needs_review and created_record_ids:
                try:
                    accept_order_in_mirakl(order_id)
                    auto_confirmed_ids.add(order_id)
                    print(f"Order {order_id} auto-accepted in Mirakl")
                except Exception as e:
                    print(f"Auto-accept failed for order {order_id}: {e}")
                    send_error_email(
                        f"Mirakl Auto-Accept Error: {order_id}",
                        f"Order {order_id} was synced to Airtable but could not be auto-accepted in Mirakl.\n\nError: {e}\n\nThe order is in Airtable with status 'New'. Set it to 'Order' when ready and the system will retry acceptance automatically."
                    )

        print(f"Done. {new_count} new line item(s) added to Airtable.")

        # Alert on orders still in WAITING_ACCEPTANCE for 3+ days (excludes just-confirmed orders)
        alert_threshold = str(date.today() - timedelta(days=3))
        at_risk = [
            o for o in orders
            if (o.get('created_date') or '')[:10] <= alert_threshold
            and o.get('order_id') not in auto_confirmed_ids
        ]
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

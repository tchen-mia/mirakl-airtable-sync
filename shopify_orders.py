import os
import requests
import smtplib
from email.mime.text import MIMEText

AIRTABLE_API_KEY = os.environ['AIRTABLE_API_KEY']
AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
AIRTABLE_TABLE_NAME = os.environ['AIRTABLE_TABLE_NAME']
SHOPIFY_STORE_URL = os.environ['SHOPIFY_STORE_URL']
SHOPIFY_API_TOKEN = os.environ['SHOPIFY_API_TOKEN']
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
ERROR_EMAIL_TO = os.environ.get('ERROR_EMAIL_TO', '')

SHOPIFY_API_VERSION = '2024-01'


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


def get_shopify_barcode_map():
    """Return dict: barcode (lowercase) → Shopify variant ID, from all Shopify products."""
    headers = {'X-Shopify-Access-Token': SHOPIFY_API_TOKEN}
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/products.json"
    params = {'limit': 250, 'fields': 'id,variants'}
    barcode_map = {}

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        for product in response.json().get('products', []):
            for variant in product.get('variants', []):
                barcode = (variant.get('barcode') or '').strip()
                if barcode:
                    barcode_map[barcode.lower()] = variant['id']
        # Shopify pagination via Link header
        next_url = None
        for part in response.headers.get('Link', '').split(','):
            if 'rel="next"' in part:
                next_url = part.split(';')[0].strip().strip('<>')
                break
        url = next_url
        params = {}  # next_url already includes params

    return barcode_map


def get_workbook_barcode_map():
    """Return dict: Airtable Workbooks record ID → barcode."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Workbooks"
    params = {'fields[]': ['Barcode'], 'pageSize': 100}
    record_map = {}

    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        for record in data.get('records', []):
            barcode = (record.get('fields', {}).get('Barcode') or '').strip()
            if barcode:
                record_map[record['id']] = barcode
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset

    return record_map


def get_airtable_records(filter_formula):
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    params = {
        'filterByFormula': filter_formula,
        'fields[]': [
            'Ariba Invoice #', 'Mirakl', 'Workbooks', 'Shopify Order ID',
            'Child Name', 'Parent Email',
            'Address Line 1', 'Address Line 2', 'City', 'State', 'Zip Code', 'Phone',
        ],
        'pageSize': 100
    }
    records = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset
    return records


def update_airtable_record(record_id, fields):
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    response = requests.patch(url, headers=headers, json={'fields': fields}, timeout=30)
    response.raise_for_status()


def update_all_records_for_order(order_id, fields):
    """Update every Airtable row for a given order ID."""
    for record in get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'"):
        update_airtable_record(record['id'], fields)


def create_shopify_order(line_items, shipping_address, email):
    """Create an order in Shopify. Returns the Shopify order ID as a string."""
    headers = {
        'X-Shopify-Access-Token': SHOPIFY_API_TOKEN,
        'Content-Type': 'application/json'
    }
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/orders.json"
    body = {
        'order': {
            'line_items': line_items,
            'shipping_address': shipping_address,
            'email': email,
            'financial_status': 'paid',
            'send_receipt': False,
            'send_fulfillment_receipt': False,
        }
    }
    response = requests.post(url, headers=headers, json=body, timeout=30)
    if not response.ok:
        print(f"Shopify order error {response.status_code}: {response.text}")
    response.raise_for_status()
    return str(response.json()['order']['id'])


def create_shopify_orders():
    """For each Airtable record with Mirakl = 'Order', create a Shopify order for book items."""
    try:
        records = get_airtable_records("{Mirakl} = 'Order'")
        if not records:
            print("No orders to send to Shopify.")
            return

        # Group records by order ID, collecting all linked workbook record IDs
        orders = {}
        for record in records:
            f = record.get('fields', {})
            order_id = f.get('Ariba Invoice #')
            if not order_id:
                continue
            if order_id not in orders:
                orders[order_id] = {'fields': f, 'workbook_record_ids': set()}
            for wb_id in f.get('Workbooks', []):
                orders[order_id]['workbook_record_ids'].add(wb_id)

        barcode_map = get_shopify_barcode_map()    # barcode → Shopify variant ID
        workbook_map = get_workbook_barcode_map()  # Airtable record ID → barcode

        created_count = 0

        for order_id, order_data in orders.items():
            try:
                f = order_data['fields']

                # Build Shopify line items from linked workbooks
                line_items = []
                for wb_record_id in order_data['workbook_record_ids']:
                    barcode = workbook_map.get(wb_record_id, '').lower()
                    if not barcode:
                        print(f"Order {order_id}: workbook {wb_record_id} has no barcode — skipping item")
                        continue
                    variant_id = barcode_map.get(barcode)
                    if not variant_id:
                        print(f"Order {order_id}: barcode {barcode!r} not found in Shopify — skipping item")
                        continue
                    line_items.append({'variant_id': variant_id, 'quantity': 1})

                if not line_items:
                    print(f"Order {order_id}: no Shopify items found — skipping")
                    continue

                # Build shipping address (split Child Name into first/last)
                name_parts = f.get('Child Name', '').split(' ', 1)
                shipping_address = {
                    'first_name': name_parts[0] if name_parts else '',
                    'last_name': name_parts[1] if len(name_parts) > 1 else '',
                    'address1': f.get('Address Line 1', ''),
                    'address2': f.get('Address Line 2', ''),
                    'city': f.get('City', ''),
                    'province_code': f.get('State', ''),
                    'zip': f.get('Zip Code', ''),
                    'country_code': 'US',
                    'phone': f.get('Phone', ''),
                }

                shopify_order_id = create_shopify_order(
                    line_items,
                    shipping_address,
                    f.get('Parent Email', '')
                )
                update_all_records_for_order(order_id, {
                    'Mirakl': 'Ordered',
                    'Shopify Order ID': shopify_order_id,
                })
                print(f"Order {order_id} → Shopify order {shopify_order_id}")
                created_count += 1

            except Exception as e:
                print(f"Failed to create Shopify order for {order_id}: {e}")
                send_error_email(
                    f"Shopify Order Error: {order_id}",
                    f"Failed to create Shopify order for Mirakl order {order_id}.\n\nError: {e}"
                )

        print(f"Done. {created_count} Shopify order(s) created.")

    except Exception as e:
        msg = f"create_shopify_orders failed: {e}"
        print(msg)
        send_error_email("Shopify Order Error", msg)
        raise


def poll_shopify_tracking():
    """
    Check Shopify fulfillments for 'Ordered' records.
    When a tracking number is found, write it to Airtable so CS can trigger Ship.
    """
    try:
        records = get_airtable_records("{Mirakl} = 'Ordered'")
        if not records:
            return

        # Collect unique Shopify order IDs
        seen = set()
        shopify_to_mirakl = {}
        for record in records:
            f = record.get('fields', {})
            mirakl_order_id = f.get('Ariba Invoice #')
            shopify_order_id = (f.get('Shopify Order ID') or '').strip()
            if mirakl_order_id and shopify_order_id and shopify_order_id not in seen:
                shopify_to_mirakl[shopify_order_id] = mirakl_order_id
                seen.add(shopify_order_id)

        headers = {'X-Shopify-Access-Token': SHOPIFY_API_TOKEN}

        for shopify_order_id, mirakl_order_id in shopify_to_mirakl.items():
            try:
                url = f"https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/orders/{shopify_order_id}/fulfillments.json"
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                for fulfillment in response.json().get('fulfillments', []):
                    tracking = (fulfillment.get('tracking_number') or '').strip()
                    if tracking:
                        update_all_records_for_order(mirakl_order_id, {'Tracking Number': tracking})
                        print(f"Order {mirakl_order_id} → tracking {tracking} pulled from Shopify")
                        break
            except Exception as e:
                print(f"Failed to poll tracking for Shopify order {shopify_order_id}: {e}")

    except Exception as e:
        msg = f"poll_shopify_tracking failed: {e}"
        print(msg)
        send_error_email("Shopify Tracking Poll Error", msg)


if __name__ == '__main__':
    create_shopify_orders()
    poll_shopify_tracking()

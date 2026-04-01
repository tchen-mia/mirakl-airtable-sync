import os
import requests
import smtplib
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


def get_airtable_records(filter_formula):
    """Fetch Airtable records matching a filter formula."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    params = {
        'filterByFormula': filter_formula,
        'fields[]': ['Ariba Invoice #', 'Mirakl', 'Type', 'Tracking Number'],
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
    all_records = get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'")
    for record in all_records:
        update_airtable_record(record['id'], fields)


def order_has_books(order_id):
    """Return True if any line item in the order has Type = Book."""
    all_records = get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'")
    for record in all_records:
        type_value = record.get('fields', {}).get('Type', [])
        if isinstance(type_value, list) and 'Book' in type_value:
            return True
    return False


def get_order_line_ids(order_id):
    """Fetch order from Mirakl and return its line IDs."""
    headers = {'Authorization': MIRAKL_API_KEY}
    response = requests.get(
        f"{MIRAKL_API_URL}/api/orders",
        headers=headers,
        params={'order_ids': order_id},
        timeout=30
    )
    if not response.ok:
        print(f"Mirakl get order error {response.status_code}: {response.text}")
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


def add_tracking_in_mirakl(order_id, tracking_number):
    """Add FedEx tracking info via Mirakl OR23."""
    headers = {
        'Authorization': MIRAKL_API_KEY,
        'Content-Type': 'application/json'
    }
    body = {
        'carrier_code': 'FEDEX',
        'carrier_name': 'FedEx',
        'carrier_standard_code': 'FEDEX',
        'carrier_url': 'https://www.fedex.com',
        'tracking_number': tracking_number
    }
    response = requests.put(
        f"{MIRAKL_API_URL}/api/orders/{order_id}/tracking",
        headers=headers,
        json=body,
        timeout=30
    )
    if not response.ok:
        print(f"Mirakl tracking error {response.status_code}: {response.text}")
    response.raise_for_status()


def ship_order_in_mirakl(order_id):
    """Mark order as shipped via Mirakl OR24."""
    headers = {
        'Authorization': MIRAKL_API_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.put(
        f"{MIRAKL_API_URL}/api/orders/{order_id}/ship",
        headers=headers,
        json={},
        timeout=30
    )
    if not response.ok:
        print(f"Mirakl ship error {response.status_code}: {response.text}")
    response.raise_for_status()


def confirm_orders():
    """
    Handle Confirm → Confirmed (books) or Confirm → Shipped (digital).
    Digital orders are auto-shipped after acceptance.
    Book orders wait for a tracking number before shipping.
    """
    try:
        records = get_airtable_records("{Mirakl} = 'Confirm'")
        if not records:
            print("No orders to confirm.")
            return

        order_ids = set()
        for record in records:
            order_id = record.get('fields', {}).get('Ariba Invoice #')
            if order_id:
                order_ids.add(order_id)

        confirmed_count = 0

        for order_id in order_ids:
            try:
                accept_order_in_mirakl(order_id)

                if order_has_books(order_id):
                    # Physical items — wait for tracking number before shipping
                    update_all_records_for_order(order_id, {'Mirakl': 'Confirmed'})
                    print(f"Order {order_id} confirmed (has books — awaiting tracking number)")
                else:
                    # Digital only — set to Confirmed, auto_ship_digital_orders() will
                    # ship it on the next run once Mirakl finishes payment processing
                    update_all_records_for_order(order_id, {'Mirakl': 'Confirmed'})
                    print(f"Order {order_id} confirmed (digital — will auto-ship once payment clears)")

                confirmed_count += 1

            except Exception as e:
                print(f"Failed to confirm order {order_id}: {e}")
                send_error_email(
                    f"Mirakl Confirm Error: Order {order_id}",
                    f"Failed to confirm order {order_id} in Mirakl.\n\nError: {e}"
                )

        print(f"Done. {confirmed_count} order(s) confirmed.")

    except Exception as e:
        msg = f"confirm_orders failed: {e}"
        print(msg)
        send_error_email("Mirakl Confirm Error", msg)
        raise


def auto_ship_digital_orders():
    """
    On each run, find digital orders in Confirmed status and try OR24.
    After acceptance, Mirakl moves orders through WAITING_DEBIT_PAYMENT before
    reaching SHIPPING. This function retries silently until the order is ready.
    """
    try:
        records = get_airtable_records("{Mirakl} = 'Confirmed'")
        if not records:
            return

        # Collect order IDs that have no book items
        order_ids = set()
        for record in records:
            order_id = record.get('fields', {}).get('Ariba Invoice #')
            if order_id:
                order_ids.add(order_id)

        for order_id in order_ids:
            if order_has_books(order_id):
                continue  # Book orders wait for CS to set Ship with tracking number
            try:
                ship_order_in_mirakl(order_id)
                update_all_records_for_order(order_id, {'Mirakl': 'Shipped'})
                print(f"Auto-shipped digital order {order_id}")
            except Exception as e:
                # Silently skip — order likely still in WAITING_DEBIT_PAYMENT
                # It will be retried on the next script run
                print(f"Order {order_id} not ready to ship yet (will retry): {e}")

    except Exception as e:
        msg = f"auto_ship_digital_orders failed: {e}"
        print(msg)
        send_error_email("Mirakl Auto-Ship Error", msg)


def ship_orders():
    """
    Handle Ship → Shipped for book orders.
    CS team enters a tracking number in Airtable and sets Mirakl = Ship.
    Script calls OR23 (tracking) + OR24 (ship) and updates status to Shipped.
    """
    try:
        records = get_airtable_records("{Mirakl} = 'Ship'")
        if not records:
            print("No orders to ship.")
            return

        order_to_tracking = {}
        for record in records:
            order_id = record.get('fields', {}).get('Ariba Invoice #')
            tracking = record.get('fields', {}).get('Tracking Number', '').strip()
            if order_id and tracking:
                order_to_tracking[order_id] = tracking
            elif order_id and order_id not in order_to_tracking:
                order_to_tracking[order_id] = None

        shipped_count = 0

        for order_id, tracking_number in order_to_tracking.items():
            if not tracking_number:
                print(f"Order {order_id} has no tracking number — skipping")
                continue
            try:
                add_tracking_in_mirakl(order_id, tracking_number)
                ship_order_in_mirakl(order_id)
                update_all_records_for_order(order_id, {'Mirakl': 'Shipped'})
                shipped_count += 1
                print(f"Shipped order {order_id} (tracking: {tracking_number})")
            except Exception as e:
                print(f"Failed to ship order {order_id}: {e}")
                send_error_email(
                    f"Mirakl Ship Error: Order {order_id}",
                    f"Failed to ship order {order_id} in Mirakl.\n\nError: {e}"
                )

        print(f"Done. {shipped_count} order(s) shipped.")

    except Exception as e:
        msg = f"ship_orders failed: {e}"
        print(msg)
        send_error_email("Mirakl Ship Error", msg)
        raise


if __name__ == '__main__':
    confirm_orders()
    auto_ship_digital_orders()
    ship_orders()

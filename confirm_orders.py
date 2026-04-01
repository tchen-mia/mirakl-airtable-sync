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
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
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


def get_records_to_confirm():
    """Fetch all Airtable records where Mirakl = 'Confirm'."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    params = {
        'filterByFormula': "{Mirakl} = 'Confirm'",
        'fields[]': ['Ariba Invoice #', 'Mirakl'],
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


def accept_order_in_mirakl(order_id):
    """Call Mirakl API to accept an order."""
    headers = {'Authorization': MIRAKL_API_KEY}
    response = requests.put(
        f"{MIRAKL_API_URL}/api/orders/{order_id}/accept",
        headers=headers,
        timeout=30
    )
    response.raise_for_status()


def update_airtable_record(record_id, fields):
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    response = requests.patch(url, headers=headers, json={'fields': fields}, timeout=30)
    response.raise_for_status()


def confirm_orders():
    try:
        records = get_records_to_confirm()

        if not records:
            print("No orders to confirm.")
            return

        # Group records by order ID so we only call Mirakl once per order
        # (multiple Airtable rows can share the same order ID for multi-item orders)
        order_to_records = {}
        for record in records:
            order_id = record.get('fields', {}).get('Ariba Invoice #')
            if order_id:
                order_to_records.setdefault(order_id, []).append(record['id'])

        confirmed_count = 0

        for order_id, record_ids in order_to_records.items():
            try:
                accept_order_in_mirakl(order_id)
                # Update all Airtable rows for this order to 'Confirmed'
                for record_id in record_ids:
                    update_airtable_record(record_id, {'Mirakl': 'Confirmed'})
                confirmed_count += 1
                print(f"Confirmed order {order_id}")
            except Exception as e:
                # Log and continue — don't let one failed order block the rest
                print(f"Failed to confirm order {order_id}: {e}")
                send_error_email(
                    f"Mirakl Confirm Error: Order {order_id}",
                    f"Failed to confirm order {order_id} in Mirakl.\n\nError: {e}"
                )

        print(f"Done. {confirmed_count} order(s) confirmed.")

    except Exception as e:
        msg = f"confirm_orders.py failed: {e}"
        print(msg)
        send_error_email("Mirakl Confirm Error", msg)
        raise


if __name__ == '__main__':
    confirm_orders()

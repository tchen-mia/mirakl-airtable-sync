import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
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
SMTP_FROM_STATEFUNDING = os.environ.get('SMTP_FROM_STATEFUNDING', '') or os.environ.get('SMTP_USER', '')
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


def send_superteacher_activation_email(to_email, order_id, child_name, activation_code):
    """Send the SuperTeacher activation code email to the customer."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        print(f"Email not configured — skipping SuperTeacher email for order {order_id}")
        return
    try:
        html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 15px; color: #222; max-width: 650px;">
            <p>Dear Parent/Guardian,</p>

            <p>We've received a 12-month Super Teacher access purchase for your student,
            <strong>{child_name}</strong>. Thank you - we're excited to welcome your student to the app!</p>

            <p>Please complete the steps below to activate your access:</p>

            <ol style="line-height: 2;">
                <li>Get Super Teacher from
                    <a href="https://apps.apple.com/app/super-teacher/id6443491064" style="color:#1a73e8;">iOS App Store</a> or
                    <a href="https://play.google.com/store/apps/details?id=com.getsuperteacher.superteacher" style="color:#1a73e8;">Android Play Store</a>
                    and open the app, or visit
                    <a href="https://superteacherapp.com" style="color:#1a73e8;">superteacherapp.com</a>.
                </li>
                <li>Tap the profile icon at the top right, then tap <strong>Upgrade</strong>.</li>
                <li>Create an account or log in to your existing Super Teacher account.</li>
                <li>Enter the confirmation code sent to your email.</li>
                <li>In the final step, instead of paying, tap <strong>Enter code</strong> at the top right,
                and choose &ldquo;School code&rdquo;. Then enter your personal one-time-use school code:
                <strong style="background-color:#FFD700; padding:2px 6px;">{activation_code}</strong></li>
            </ol>

            <p>If you have any questions while using the app, tap the profile icon at the top right,
            and tap &ldquo;For parents&rdquo; to access the &ldquo;Help and FAQ&rdquo; section.
            Alternatively, you may also email
            <a href="mailto:support@getsuperteacher.com" style="color:#1a73e8;">support@getsuperteacher.com</a>,
            and their team will get back to you within 1-3 business days.</p>

            <p>Thank you for your kind support. Have a great day!</p>

            <p>Warm Regards,<br><strong>Miaplaza Team</strong></p>
        </div>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Action Needed: Your Super Teacher App Purchase from Step Up MyScholarShop"
        msg['From'] = f"State Funding Programs <{SMTP_FROM_STATEFUNDING}>"
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"SuperTeacher activation email sent to {to_email} for order {order_id}")
    except Exception as e:
        print(f"Failed to send SuperTeacher email for order {order_id}: {e}")
        send_error_email(
            f"SuperTeacher Email Failed: Order {order_id}",
            f"Could not send activation code email for order {order_id} to {to_email}.\n\nActivation code: {activation_code}\n\nError: {e}"
        )


def get_airtable_records(filter_formula):
    """Fetch Airtable records matching a filter formula."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    params = {
        'filterByFormula': filter_formula,
        'fields[]': ['Ariba Invoice #', 'Mirakl', 'Type', 'Tracking Number', 'Site', 'Parent Email', 'Child Name'],
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


# Types that require a manually entered tracking number before shipping
MANUAL_TRACKING_TYPES = {'Book', 'SuperTeacher'}


def order_needs_manual_tracking(order_id):
    """Return True if any line item requires a manually entered tracking number."""
    all_records = get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'")
    for record in all_records:
        type_value = record.get('fields', {}).get('Type', [])
        if isinstance(type_value, list) and MANUAL_TRACKING_TYPES & set(type_value):
            return True
    return False


def get_order_from_mirakl(order_id):
    """Fetch order details from Mirakl. Returns the order dict."""
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
    return orders[0]


def get_order_line_ids(order_id):
    """Fetch order from Mirakl and return its line IDs."""
    order = get_order_from_mirakl(order_id)
    return [line['order_line_id'] for line in order.get('order_lines', [])]


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
        'carrier_code': 'fedex',
        'carrier_name': 'FedEx',
        'carrier_standard_code': 'fedex',
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
    Handle Confirm → Confirmed for orders flagged New - Review that CS has manually approved.
    Clean orders are auto-confirmed at sync time; this handles the review exceptions.
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
                update_all_records_for_order(order_id, {'Mirakl': 'Confirmed'})
                print(f"Order {order_id} confirmed — set Mirakl to Ship when ready")
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


SITE_PREFIX = {'MIA': 'MIA', 'MP': 'MP', 'MP+': 'MPP'}


def get_site_prefix_for_order(order_id):
    """Return the tracking number prefix based on the Site of the first digital line item."""
    records = get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'")
    for record in records:
        site = record.get('fields', {}).get('Site', '')
        if site in SITE_PREFIX:
            return SITE_PREFIX[site]
    return 'DIGITAL'


def ship_orders():
    """
    Handle Ship → Shipped for all orders.
    CS team sets Mirakl = Ship (and enters a tracking number for book/SuperTeacher orders).
    Digital orders auto-generate a tracking number if none is provided.
    Script calls OR23 (tracking) + OR24 (ship), updates status to Shipped,
    and sends the activation code email for SuperTeacher orders.
    """
    try:
        records = get_airtable_records("{Mirakl} = 'Ship'")
        if not records:
            print("No orders to ship.")
            return

        # Collect tracking numbers and order metadata per order ID
        order_to_tracking = {}
        order_metadata = {}
        for record in records:
            f = record.get('fields', {})
            order_id = f.get('Ariba Invoice #')
            tracking = (f.get('Tracking Number') or '').strip()
            if order_id and tracking:
                order_to_tracking[order_id] = tracking
            elif order_id and order_id not in order_to_tracking:
                order_to_tracking[order_id] = None
            if order_id and order_id not in order_metadata:
                order_metadata[order_id] = {
                    'email': f.get('Parent Email', ''),
                    'child_name': f.get('Child Name', ''),
                    'types': set(),
                }
            if order_id:
                for t in (f.get('Type') or []):
                    order_metadata[order_id]['types'].add(t)

        shipped_count = 0

        for order_id, tracking_number in order_to_tracking.items():
            if not tracking_number:
                if order_needs_manual_tracking(order_id):
                    print(f"Order {order_id} has no tracking number — skipping")
                    continue
                # Digital order — auto-generate tracking number
                prefix = get_site_prefix_for_order(order_id)
                tracking_number = f"{prefix}-{order_id}"
            try:
                add_tracking_in_mirakl(order_id, tracking_number)
                ship_order_in_mirakl(order_id)
                update_all_records_for_order(order_id, {'Mirakl': 'Shipped', 'Tracking Number': tracking_number})
                shipped_count += 1
                print(f"Shipped order {order_id} (tracking: {tracking_number})")

                # Send activation code email for SuperTeacher orders
                meta = order_metadata.get(order_id, {})
                if 'SuperTeacher' in meta.get('types', set()):
                    send_superteacher_activation_email(
                        to_email=meta['email'],
                        order_id=order_id,
                        child_name=meta['child_name'],
                        activation_code=tracking_number,
                    )

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
    ship_orders()

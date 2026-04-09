import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Environment ───────────────────────────────────────────────────────────────
AIRTABLE_API_KEY = os.environ['AIRTABLE_API_KEY']
AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
AIRTABLE_TABLE_NAME = os.environ['AIRTABLE_TABLE_NAME']
SHOPIFY_STORE_URL = os.environ['SHOPIFY_STORE_URL']
SHOPIFY_API_TOKEN = os.environ['SHOPIFY_API_TOKEN']
MIRAKL_API_URL = os.environ['MIRAKL_API_URL']
MIRAKL_API_KEY = os.environ['MIRAKL_API_KEY']
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_BOOKS = os.environ.get('SMTP_FROM_BOOKS', '') or os.environ.get('SMTP_USER', '')
SMTP_FROM_STATEFUNDING = os.environ.get('SMTP_FROM_STATEFUNDING', '') or os.environ.get('SMTP_USER', '')
ERROR_EMAIL_TO = os.environ.get('ERROR_EMAIL_TO', '')

SHOPIFY_API_VERSION = '2024-01'
SITE_PREFIX = {'MIA': 'MIA', 'MP': 'MP', 'MP+': 'MPP'}


# ── Email ─────────────────────────────────────────────────────────────────────

def send_error_email(subject, body):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ERROR_EMAIL_TO]):
        print(f"Email not configured. Error was: {subject}")
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
        print(f"Error email sent to {ERROR_EMAIL_TO}")
    except Exception as e:
        print(f"Failed to send error email: {e}")


def send_order_confirmation_email(to_email, order_id, workbook_items, child_name,
                                   address_line1, address_line2, city, state, zip_code, phone):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        print(f"Email not configured — skipping confirmation email for order {order_id}")
        return False
    try:
        address_parts = [address_line1]
        if address_line2:
            address_parts.append(address_line2)
        address_parts.append(f"{city}, {state} {zip_code}".strip())
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
                <li>Recipient full name: <strong>{child_name}</strong></li>
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
        msg['Subject'] = f"Your Workbook Order ({order_id}) Has Been Processed"
        msg['From'] = f"Miaplaza Workbooks <{SMTP_FROM_BOOKS}>"
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Workbook confirmation email sent to {to_email} for order {order_id}")
        return True
    except Exception as e:
        print(f"Failed to send workbook confirmation email for order {order_id}: {e}")
        return False


def send_superteacher_activation_email(to_email, order_id, child_name, activation_code):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        print(f"Email not configured — skipping SuperTeacher email for order {order_id}")
        return False
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
        msg['Subject'] = "Action Needed: Your Super Teacher App Purchase from Step Up MyScholarShop"
        msg['From'] = f"State Funding Programs <{SMTP_FROM_STATEFUNDING}>"
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"SuperTeacher activation email sent to {to_email} for order {order_id}")
        return True
    except Exception as e:
        print(f"Failed to send SuperTeacher email for order {order_id}: {e}")
        return False


# ── Airtable ──────────────────────────────────────────────────────────────────

def get_airtable_records(filter_formula, fields=None):
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    params = {'filterByFormula': filter_formula, 'pageSize': 100}
    if fields:
        params['fields[]'] = fields
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
    for record in get_airtable_records(f"{{Ariba Invoice #}} = '{order_id}'"):
        update_airtable_record(record['id'], fields)


# ── Shopify ───────────────────────────────────────────────────────────────────

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
        next_url = None
        for part in response.headers.get('Link', '').split(','):
            if 'rel="next"' in part:
                next_url = part.split(';')[0].strip().strip('<>')
                break
        url = next_url
        params = {}

    return barcode_map


def get_workbook_map():
    """Return dict: Airtable Workbooks record ID → {barcode, name}."""
    headers = {'Authorization': f'Bearer {AIRTABLE_API_KEY}'}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Workbooks"
    params = {'fields[]': ['Barcode', 'Name'], 'pageSize': 100}
    record_map = {}

    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        for record in data.get('records', []):
            f = record.get('fields') or {}
            barcode = (f.get('Barcode') or '').strip()
            name = (f.get('Name') or '').strip()
            record_map[record['id']] = {'barcode': barcode, 'name': name}
        offset = data.get('offset')
        if not offset:
            break
        params['offset'] = offset

    return record_map


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


# ── Mirakl ────────────────────────────────────────────────────────────────────

def get_mirakl_order_state(order_id):
    """Return the current Mirakl order state code."""
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
    return orders[0].get('order_state_code', '')


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


def add_tracking_in_mirakl(order_id, tracking_number):
    """Add tracking info via Mirakl OR23."""
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


# ── Main functions ────────────────────────────────────────────────────────────

def process_orders():
    """
    Process all orders with Mirakl = 'Order':
    - Accepts in Mirakl if still WAITING_ACCEPTANCE (handles New-Review orders)
    - SuperTeacher: sends activation email using ST Code
    - Books: creates Shopify order, sends workbook confirmation email → Ordered
    - Digital only (no books): auto-ships with generated tracking → Shipped
    - Mixed book + digital/ST: creates Shopify order, sends ST email if applicable → Ordered
    """
    try:
        records = get_airtable_records(
            "{Mirakl} = 'Order'",
            fields=[
                'Ariba Invoice #', 'Type', 'Workbooks', 'Quantity',
                'Child Name', 'Parent Email',
                'Address Line 1', 'Address Line 2', 'City', 'State', 'Zip Code', 'Phone',
                'ST Code', 'Site',
            ]
        )
        if not records:
            print("No orders to process.")
            return

        # Group records by order ID
        orders = {}
        for record in records:
            f = record.get('fields') or {}
            order_id = f.get('Ariba Invoice #')
            if not order_id:
                continue
            if order_id not in orders:
                orders[order_id] = {
                    'fields': f,
                    'workbook_quantities': {},  # wb_record_id → quantity
                    'types': set(),
                    'st_code': '',
                    'site': '',
                }
            qty = int(f.get('Quantity') or 1)
            for wb_id in (f.get('Workbooks') or []):
                orders[order_id]['workbook_quantities'][wb_id] = qty
            for t in (f.get('Type') or []):
                orders[order_id]['types'].add(t)
            st_code = (f.get('ST Code') or '').strip()
            if st_code:
                orders[order_id]['st_code'] = st_code
            site = (f.get('Site') or '').strip()
            if site:
                orders[order_id]['site'] = site

        any_books = any('Book' in o['types'] for o in orders.values())
        barcode_map = get_shopify_barcode_map() if any_books else {}
        workbook_map = get_workbook_map() if any_books else {}
        processed_count = 0

        for order_id, order_data in orders.items():
            log = []
            try:
                f = order_data['fields']
                types = order_data['types']
                has_books = 'Book' in types
                has_superteacher = 'SuperTeacher' in types
                st_code = order_data['st_code']
                email = f.get('Parent Email', '')
                child_name = f.get('Child Name', '')

                # Accept in Mirakl if still waiting (New-Review orders skipped OR21 at sync time)
                state = get_mirakl_order_state(order_id)
                if state == 'WAITING_ACCEPTANCE':
                    accept_order_in_mirakl(order_id)
                    log.append("Accepted in Mirakl")

                # SuperTeacher — send activation email
                if has_superteacher:
                    if not st_code:
                        log.append("Error: ST Code missing — activation email not sent")
                        update_all_records_for_order(order_id, {'Automation Log': ' | '.join(log)})
                        send_error_email(
                            f"ST Code Missing: Order {order_id}",
                            f"Order {order_id} has SuperTeacher but no ST Code was entered.\n\n"
                            f"Please enter the ST Code in the ST Code column and set Mirakl back to 'Order'."
                        )
                        continue
                    st_ok = send_superteacher_activation_email(
                        to_email=email,
                        order_id=order_id,
                        child_name=child_name,
                        activation_code=st_code,
                    )
                    if st_ok:
                        log.append("ST activation email sent")
                    else:
                        log.append("Error: ST activation email failed")
                        send_error_email(
                            f"SuperTeacher Email Failed: Order {order_id}",
                            f"Could not send activation email for order {order_id} to {email}.\n\n"
                            f"ST Code: {st_code}"
                        )

                # Books — create Shopify order
                if has_books:
                    line_items = []
                    workbook_items = []  # list of (name, quantity) for confirmation email
                    for wb_record_id, qty in order_data['workbook_quantities'].items():
                        wb_info = workbook_map.get(wb_record_id, {})
                        barcode = wb_info.get('barcode', '').lower()
                        name = wb_info.get('name', '')
                        if not barcode:
                            log.append(f"Error: workbook {wb_record_id} has no barcode")
                            continue
                        variant_id = barcode_map.get(barcode)
                        if not variant_id:
                            log.append(f"Error: barcode {barcode!r} not found in Shopify")
                            continue
                        line_items.append({'variant_id': variant_id, 'quantity': qty})
                        if name:
                            workbook_items.append((name, qty))

                    if not line_items:
                        log.append("Error: no valid Shopify line items found")
                        update_all_records_for_order(order_id, {'Automation Log': ' | '.join(log)})
                        send_error_email(
                            f"Shopify Order Error: {order_id}",
                            f"Order {order_id} has Book items but none matched a Shopify variant.\n\n"
                            f"Log: {' | '.join(log)}"
                        )
                        continue

                    name_parts = (child_name or '').split(' ', 1)
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

                    shopify_order_id = create_shopify_order(line_items, shipping_address, email)
                    log.append(f"Shopify order {shopify_order_id} created")

                    wb_ok = send_order_confirmation_email(
                        to_email=email,
                        order_id=order_id,
                        workbook_items=workbook_items,
                        child_name=child_name,
                        address_line1=f.get('Address Line 1', ''),
                        address_line2=f.get('Address Line 2', ''),
                        city=f.get('City', ''),
                        state=f.get('State', ''),
                        zip_code=f.get('Zip Code', ''),
                        phone=f.get('Phone', ''),
                    )
                    if wb_ok:
                        log.append("Workbook confirmation email sent")
                    else:
                        log.append("Error: workbook confirmation email failed")
                        send_error_email(
                            f"Workbook Email Failed: Order {order_id}",
                            f"Could not send workbook confirmation email for order {order_id} to {email}.\n\n"
                            f"Shopify order {shopify_order_id} was created successfully."
                        )

                    update_all_records_for_order(order_id, {
                        'Mirakl': 'Ordered',
                        'Shopify Order ID': shopify_order_id,
                        'Automation Log': ' | '.join(log),
                    })
                    print(f"Order {order_id} → Shopify {shopify_order_id} (Ordered)")

                else:
                    # No books — digital and/or SuperTeacher: auto-ship immediately
                    if has_superteacher and st_code:
                        tracking_number = st_code
                    else:
                        prefix = SITE_PREFIX.get(order_data['site'], 'DIGITAL')
                        tracking_number = f"{prefix}-{order_id}"

                    add_tracking_in_mirakl(order_id, tracking_number)
                    log.append(f"Tracking {tracking_number} added in Mirakl")
                    ship_order_in_mirakl(order_id)
                    log.append("Shipped in Mirakl")

                    update_all_records_for_order(order_id, {
                        'Mirakl': 'Shipped',
                        'Tracking Number': tracking_number,
                        'Automation Log': ' | '.join(log),
                    })
                    print(f"Order {order_id} → Shipped (tracking: {tracking_number})")

                processed_count += 1

            except Exception as e:
                log.append(f"Error: {e}")
                print(f"Failed to process order {order_id}: {e}")
                try:
                    update_all_records_for_order(order_id, {'Automation Log': ' | '.join(log)})
                except Exception:
                    pass
                send_error_email(
                    f"Order Processing Error: {order_id}",
                    f"Failed to process order {order_id}.\n\nLog: {' | '.join(log)}\n\nError: {e}"
                )

        print(f"Done. {processed_count} order(s) processed.")

    except Exception as e:
        msg = f"process_orders failed: {e}"
        print(msg)
        send_error_email("Order Processing Error", msg)
        raise


def poll_shopify_tracking():
    """
    Check Shopify fulfillments for 'Ordered' records.
    When tracking is found, call OR23+OR24 and update Airtable to Shipped.
    """
    try:
        records = get_airtable_records(
            "{Mirakl} = 'Ordered'",
            fields=['Ariba Invoice #', 'Shopify Order ID', 'Automation Log']
        )
        if not records:
            return

        seen = set()
        order_map = {}  # shopify_order_id → {mirakl_order_id, existing_log}
        for record in records:
            f = record.get('fields') or {}
            mirakl_order_id = f.get('Ariba Invoice #')
            shopify_order_id = (f.get('Shopify Order ID') or '').strip()
            if mirakl_order_id and shopify_order_id and shopify_order_id not in seen:
                order_map[shopify_order_id] = {
                    'mirakl_order_id': mirakl_order_id,
                    'existing_log': (f.get('Automation Log') or '').strip(),
                }
                seen.add(shopify_order_id)

        shopify_headers = {'X-Shopify-Access-Token': SHOPIFY_API_TOKEN}

        for shopify_order_id, data in order_map.items():
            mirakl_order_id = data['mirakl_order_id']
            existing_log = data['existing_log']
            try:
                url = (
                    f"https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}"
                    f"/orders/{shopify_order_id}/fulfillments.json"
                )
                response = requests.get(url, headers=shopify_headers, timeout=30)
                response.raise_for_status()
                for fulfillment in response.json().get('fulfillments', []):
                    tracking = (fulfillment.get('tracking_number') or '').strip()
                    if tracking:
                        log = [existing_log] if existing_log else []
                        add_tracking_in_mirakl(mirakl_order_id, tracking)
                        log.append(f"FedEx tracking {tracking} synced")
                        ship_order_in_mirakl(mirakl_order_id)
                        log.append("Shipped in Mirakl")
                        update_all_records_for_order(mirakl_order_id, {
                            'Tracking Number': tracking,
                            'Mirakl': 'Shipped',
                            'Automation Log': ' | '.join(log),
                        })
                        print(f"Order {mirakl_order_id} → tracking {tracking}, Shipped")
                        break
            except Exception as e:
                print(f"Failed to process tracking for Shopify order {shopify_order_id}: {e}")
                send_error_email(
                    f"Tracking Poll Error: {mirakl_order_id}",
                    f"Failed to sync tracking/shipping for order {mirakl_order_id} "
                    f"(Shopify {shopify_order_id}).\n\nError: {e}"
                )

    except Exception as e:
        msg = f"poll_shopify_tracking failed: {e}"
        print(msg)
        send_error_email("Tracking Poll Error", msg)


if __name__ == '__main__':
    process_orders()
    poll_shopify_tracking()

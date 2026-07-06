import json
import os
import re
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

AIRTABLE_API_KEY = os.environ['AIRTABLE_API_KEY']
# Legacy single-base config — optional now. When BOOK_ORDER_BASES is set these are
# ignored; when it is absent they are required (validated in build_bases()).
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')
BOOK_ORDER_TABLES = os.environ.get('BOOK_ORDER_TABLES')
SHOPIFY_STORE_URL = os.environ['SHOPIFY_STORE_URL']
SHOPIFY_API_TOKEN = os.environ['SHOPIFY_API_TOKEN']
SHOPIFY_API_VERSION = '2024-01'
# Multi-base config (optional, authoritative when set). JSON array of objects:
#   [{"base_id": "app...", "tables": ["T1","T2"],
#     "invoice_fields": {"T2": "PO#"}, "api_key": "pat...", "tag_prefix": "..."}]
# See build_bases() for field semantics and the legacy fallback.
BOOK_ORDER_BASES = os.environ.get('BOOK_ORDER_BASES', '').strip()
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT') or 587)
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_BOOKS = os.environ.get('SMTP_FROM_BOOKS', '') or os.environ.get('SMTP_USER', '')
ERROR_EMAIL_TO = os.environ.get('ERROR_EMAIL_TO', '')

# Per-table override of which column to use as the invoice number in the email subject.
# Format: JSON object e.g. {"Table A": "PO#", "Table B": "CW Receipt"}
# Tables not listed default to "Invoice #". Used only by the legacy single-base path;
# in multi-base mode each base carries its own invoice_fields map.
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


# ── Airtable helpers (base- and table-parameterized) ─────────────────────────

def get_records(base_id, table_name, filter_formula, fields=None, api_key=None):
    headers = {'Authorization': f'Bearer {api_key or AIRTABLE_API_KEY}'}
    url = f'https://api.airtable.com/v0/{base_id}/{requests.utils.quote(table_name, safe="")}'
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


def update_record(base_id, table_name, record_id, fields, api_key=None):
    headers = {
        'Authorization': f'Bearer {api_key or AIRTABLE_API_KEY}',
        'Content-Type': 'application/json',
    }
    url = f'https://api.airtable.com/v0/{base_id}/{requests.utils.quote(table_name, safe="")}/{record_id}'
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
        print(f'Confirmation email sent for order {order_number}')
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


def get_workbook_map(base_id, api_key=None):
    """Return {airtable_record_id: {'barcode': str, 'name': str}} from the base's
    Workbooks table. Record IDs are base-scoped, so each base has its own map."""
    headers = {'Authorization': f'Bearer {api_key or AIRTABLE_API_KEY}'}
    url = f'https://api.airtable.com/v0/{base_id}/Workbooks'
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


def order_idempotency_tag(record_id, tag_prefix=''):
    """Tag used to make order creation idempotent per Airtable record.

    tag_prefix namespaces the tag by base (`atid-<prefix>-<record_id>`) so that
    identical record IDs across different bases cannot false-match. An empty
    prefix yields the original `atid-<record_id>` form, which the legacy
    single-base config uses so its pre-existing order tags still match.
    """
    if tag_prefix:
        return f'atid-{tag_prefix}-{record_id}'
    return f'atid-{record_id}'


def find_existing_order(record_id, tag_prefix=''):
    """Return (order_id, order_number) for an order already created from this
    Airtable record, else None. Used to avoid duplicate orders if two runs overlap
    or if a previous run created the order but failed to write the ID back.

    REST orders.json can't filter by tag, so we query the GraphQL Admin API. When a
    tag_prefix is set we also match the un-prefixed legacy tag, so orders created
    before a base was namespaced are still recovered (no migration window).
    """
    headers = {
        'X-Shopify-Access-Token': SHOPIFY_API_TOKEN,
        'Content-Type': 'application/json',
    }
    url = f'https://{SHOPIFY_STORE_URL}/admin/api/{SHOPIFY_API_VERSION}/graphql.json'
    query = '''
    query($q: String!) {
      orders(first: 1, query: $q) {
        edges { node { id name } }
      }
    }'''
    tags = [order_idempotency_tag(record_id, tag_prefix)]
    if tag_prefix:
        tags.append(order_idempotency_tag(record_id, ''))
    q = ' OR '.join(f'tag:{t}' for t in tags)
    variables = {'q': q}
    r = requests.post(url, headers=headers, json={'query': query, 'variables': variables}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get('errors'):
        # Don't block creation on a lookup failure, but surface it in logs.
        print(f'  GraphQL order lookup error for {record_id}: {data["errors"]}')
        return None
    edges = data.get('data', {}).get('orders', {}).get('edges', [])
    if not edges:
        return None
    node = edges[0]['node']
    # node['id'] is "gid://shopify/Order/123456"; node['name'] is "#1001".
    order_id = node['id'].rsplit('/', 1)[-1]
    order_number = node['name'].lstrip('#')
    return str(order_id), str(order_number)


def create_shopify_order(line_items, shipping_address, email, record_id, tag_prefix=''):
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
            # Idempotency key: lets find_existing_order() detect this order on a
            # later run so we never create a duplicate for the same record.
            'tags': order_idempotency_tag(record_id, tag_prefix),
        }
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    # Do NOT log r.text — the Shopify order response echoes customer name, email,
    # and shipping address (PII). Status code only.
    print(f'Shopify response {r.status_code}')
    r.raise_for_status()
    order = r.json()['order']
    return str(order['id']), str(order['order_number'])


# ── Per-table processing ──────────────────────────────────────────────────────

def process_table(base, table_name, barcode_map, workbook_map):
    base_id = base['base_id']
    api_key = base['api_key']
    invoice_fields = base['invoice_fields']
    tag_prefix = base['tag_prefix']

    formula = "AND(SEARCH('Submit Book Order', {Status}), NOT({Shopify Order ID}))"
    records = get_records(base_id, table_name, formula, api_key=api_key)
    print(f'  [{base_id}] {table_name}: {len(records)} pending order(s)')

    for record in records:
        f = record.get('fields', {})
        record_id = record['id']
        log = []

        ship_name = (f.get('Parent Name') or f.get('Student Name') or f.get('Child Name') or '').strip()
        parent_email = (f.get('Parent Email') or f.get('Account Email') or '').strip()
        required = ['Address Line 1', 'City', 'State', 'Zip Code']
        missing = [k for k in required if not (f.get(k) or '').strip()]
        if not ship_name:
            missing.insert(0, 'Parent Name / Student Name / Child Name')
        if not parent_email:
            missing.insert(0, 'Parent Email / Account Email')
        if missing:
            msg = f'ERROR: missing required field(s): {", ".join(missing)}'
            log.append(msg)
            print(f'  {msg} — skipping record {record_id}')
            update_record(base_id, table_name, record_id, {'Automation Log': ' | '.join(log)}, api_key=api_key)
            send_error_email(
                f'Book Order Error: {table_name} / {record_id}',
                f'Cannot create Shopify order for record {record_id} in "{table_name}".\n\nLog: {" | ".join(log)}',
            )
            continue

        linked = f.get('Workbooks Ordered') or f.get('Workbooks') or []
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
                update_record(base_id, table_name, record_id, {'Automation Log': ' | '.join(log)}, api_key=api_key)
                send_error_email(
                    f'Book Order Error: {table_name} / {record_id}',
                    f'Could not create Shopify order for record {record_id} in "{table_name}".\n\nLog: {" | ".join(log)}',
                )
            continue

        full_name = ship_name
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
            # Idempotency check: if an order for this record already exists in
            # Shopify (overlapping run, or a prior run that created the order but
            # failed to write the ID back), recover it instead of creating a
            # duplicate. The confirmation email was already sent that time, so we
            # only repair the Airtable record here.
            existing = find_existing_order(record_id, tag_prefix)
            if existing:
                order_id, order_number = existing
                log.append(f'Shopify order #{order_number} already exists for this record — self-heal, skipped creation')
                update_record(base_id, table_name, record_id, {
                    'Shopify Order ID': order_id,
                    'Automation Log': ' | '.join(log),
                }, api_key=api_key)
                print(f'  Order #{order_number} already existed for record {record_id} — wrote ID back, no duplicate created')
                continue

            order_id, order_number = create_shopify_order(line_items, shipping_address, parent_email, record_id, tag_prefix)
            invoice_field = invoice_fields.get(table_name, DEFAULT_INVOICE_FIELD)
            # Fall back to 'Ariba Invoice #' (used by the Step Up / Mirakl tables)
            # before the Shopify order number. Tables without that field are
            # unaffected — f.get() returns None there.
            invoice_number = f.get(invoice_field) or f.get('Ariba Invoice #') or order_number
            log.append(f'Shopify order #{order_number} created ({len(line_items)} item(s), qty {quantity})')
            update_record(base_id, table_name, record_id, {
                'Shopify Order ID': order_id,
                'Automation Log': ' | '.join(log),
            }, api_key=api_key)
            print(f'  Created Shopify order #{order_number} for record {record_id}')
            send_order_confirmation_email(
                to_email=parent_email,
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
            update_record(base_id, table_name, record_id, {'Automation Log': ' | '.join(log)}, api_key=api_key)
            print(f'  ERROR creating order for record {record_id} in {table_name}: {e}')
            send_error_email(
                f'Book Order Error: {table_name} / {record_id}',
                f'Failed to create Shopify order for record {record_id} in "{table_name}".\n\nLog: {" | ".join(log)}\n\nError: {e}',
            )


# ── Config ─────────────────────────────────────────────────────────────────────

def build_bases():
    """Return a normalized list of base configs, each a dict with keys:
    base_id, tables (list), invoice_fields (dict), api_key, tag_prefix.

    BOOK_ORDER_BASES (a JSON array) is authoritative when set; otherwise fall back
    to a single base built from the legacy AIRTABLE_BASE_ID + BOOK_ORDER_TABLES
    (+ BOOK_ORDER_INVOICE_FIELDS) env vars, so existing single-base setups are
    unchanged.
    """
    if BOOK_ORDER_BASES:
        parsed = json.loads(BOOK_ORDER_BASES)
        bases = []
        for entry in parsed:
            base_id = entry['base_id']
            bases.append({
                'base_id': base_id,
                'tables': [t.strip() for t in entry.get('tables', []) if t and t.strip()],
                'invoice_fields': entry.get('invoice_fields') or {},
                'api_key': entry.get('api_key') or AIRTABLE_API_KEY,
                # Default: namespace the idempotency tag with the base id so record
                # ids can't collide across bases. Set "tag_prefix": "" in the config
                # to opt a base out (bare tag) — e.g. cosmetic parity with legacy.
                'tag_prefix': base_id if entry.get('tag_prefix') is None else entry['tag_prefix'],
            })
        return bases

    # Legacy single-base fallback — behavior identical to before.
    if not AIRTABLE_BASE_ID or not BOOK_ORDER_TABLES:
        raise RuntimeError(
            'No book-order config found. Set BOOK_ORDER_BASES (JSON), or both '
            'AIRTABLE_BASE_ID and BOOK_ORDER_TABLES.'
        )
    return [{
        'base_id': AIRTABLE_BASE_ID,
        'tables': [t.strip() for t in BOOK_ORDER_TABLES.split(',') if t.strip()],
        'invoice_fields': INVOICE_FIELD_BY_TABLE,
        'api_key': AIRTABLE_API_KEY,
        'tag_prefix': '',  # bare tag — matches all pre-existing single-base orders
    }]


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    bases = build_bases()
    total_tables = sum(len(b['tables']) for b in bases)
    print(f'Processing {total_tables} table(s) across {len(bases)} base(s)...')

    # Shopify is base-independent — fetch the barcode map once and share it.
    barcode_map = get_shopify_barcode_map()
    print(f'Loaded {len(barcode_map)} Shopify variant barcodes')

    for base in bases:
        base_id = base['base_id']
        print(f'=== Base {base_id}: {len(base["tables"])} table(s) ===')
        # workbook_map is base-specific (keyed by that base's Airtable record IDs).
        workbook_map = get_workbook_map(base_id, api_key=base['api_key'])
        print(f'  Loaded {len(workbook_map)} Workbook records for {base_id}')
        for table_name in base['tables']:
            process_table(base, table_name, barcode_map, workbook_map)


if __name__ == '__main__':
    main()

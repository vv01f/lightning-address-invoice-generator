#!/usr/bin/env python3
import requests
import json
import logging
import argparse
import sys
import re
import urllib
from datetime import datetime
import bech32

def get_payurl(lnaddress):
    parts = lnaddress.split('@')
    if len(parts) != 2:
        raise ValueError(f"Errorm possibly malformed LN Address: {lnaddress}")
    domain = parts[1]
    username = parts[0]
    transform_url = "https://" + domain + "/.well-known/lnurlp/" + username
    logging.info("Transformed URL:" + transform_url)
    return transform_url

def get_url(path, headers):
    response = requests.get(path, headers=headers)
    return response.text

def get_comment_length(datablock: dict) -> int:
    """
    Prüft, die zulässige Länge eines Kommentars für eine Invoice.

    Args:
        datablock (dict): Ein Dictionary, das die Bolt11/Invoice-Daten enthält.
                          Erwartet ggf. den Schlüssel 'commentAllowed'.

    Returns:
        int: 0, wenn commentAllowed nicht gesetzt, sonst Maximallänge.
    """
    # Robust prüfen: Wenn 'commentAllowed' nicht existiert, False zurückgeben
    return int(datablock.get("commentAllowed", 0))

def get_bolt11(lnaddress, amount=None, comment=None):
    try:
        purl = get_payurl(lnaddress)
        json_content = get_url(path=purl, headers={}).strip()
        datablock = json.loads(json_content)

        lnurlpay = datablock["callback"]
        min_amount = int(datablock["minSendable"])
        max_amount = int(datablock["maxSendable"])
        comment_allowed = int(get_comment_length(datablock))

        logging.info("min. amount: " + str(min_amount))
        logging.info("max. amount: " + str(max_amount))
        logging.info("comment allowed: " + str(comment_allowed))

        if amount is not None:
            amount_msat = int(amount * 1000)
            if amount_msat < min_amount:
                return {
                    "status": "error",
                    "msg": f"Amount too small, must be in range {min_amount // 1000} and {max_amount // 1000} sat"
                }
            elif amount_msat > max_amount:
                return {
                    "status": "error",
                    "msg": f"Amount too big, must be in range {min_amount // 1000} and {max_amount // 1000} sat"
                }
        else:
            amount_msat = None

        logging.info("amount: " + str(amount))

        # Start building the query
        query_params = {}

        # Omit amount when None
        if amount_msat is not None:
            query_params["amount"] = str(amount_msat)

        # If comment is allowed, truncate if necessary and add to query
        if comment_allowed > 0 and comment:
            if len(comment) > comment_allowed:
                logging.info(f"Comment truncated to {comment_allowed} characters")
                comment = comment[:comment_allowed]
            query_params["comment"] = comment

        # Build full query URL
        encoded_query = urllib.parse.urlencode(query_params)
        payquery = f"{lnurlpay}?{encoded_query}"

        logging.info(f"LNURL pay query: {payquery}")

        # Resolve query URL
        ln_res = get_url(path=payquery, headers={})
        pr_dict = json.loads(ln_res)

        if 'pr' in pr_dict:
            return {"status": "ok", "bolt11": pr_dict['pr']}
        elif 'reason' in pr_dict:
            return {"status": "error", "msg": pr_dict['reason']}
        else:
            return {"status": "error", "msg": "Unexpected response format"}

    except Exception as e:
        logging.error("in get_bolt11: " + str(e))
        return {"status": "error", "msg": str(e)}
        # ~ logging.error("in get bolt11 : "  + str(e))
        # ~ return {'status': 'error', 'msg': 'Cannot make a Bolt11, are you sure the address `' + str(lnaddress) + '` is valid and the amount withing the allowed range [' + str(min_amount // 1000) + '; ' + str(max_amount // 1000) + '] Satoshi?'}

def parse_positional_args(argv):
    lnaddress = None
    amount = None

    for arg in argv:
        # Detect email-like LN address (must contain one @ and at least one dot after it)
        if re.match(r"^[^@]+@[^@]+\.[^@]+$", arg):
            lnaddress = arg
        # Detect valid integer amount (non-negative)
        elif arg.isdigit():
            amount = int(arg)

    return lnaddress, amount

# Helper: 5-bit group to integer
def from_words(words):
    value = 0
    for w in words:
        value = (value << 5) | w
    return value

# Helper: 5-bit group to bytes
def words_to_bytes(words):
    bits = 0
    bit_buf = 0
    output = bytearray()
    for w in words:
        bit_buf = (bit_buf << 5) | w
        bits += 5
        while bits >= 8:
            bits -= 8
            output.append((bit_buf >> bits) & 0xFF)
    return bytes(output)

def parse_tags(words):
    tags = {}
    i = 0
    while i + 3 <= len(words):
        tag_int = int(words[i])
        tag_char = chr(tag_int + ord('a'))

        data_length = (words[i + 1] << 5) | words[i + 2]
        data_start = i + 3
        data_end = data_start + data_length

        if data_end > len(words):
            print("⚠️ Tag data length goes beyond available words, skipping.")
            break

        data_words = words[data_start:data_end]

        # Debugging output to track what is being parsed
        print(f"🔍 Found tag: {tag_char} with {data_length} words: {data_words}")

        match tag_char:
            case 'p': # Preimage hash (mandatory)
                tags['payment_hash'] = words_to_bytes(data_words).hex()
            case 'd': # Human-readable description (optional)
                tags['description'] = words_to_bytes(data_words).decode('utf-8', errors='ignore')
            # ~ case 'h': # SHA256 hash of description (instead of d)
            case 'x': # Expiry in seconds
                tags['expiry'] = from_words(data_words)
            # ~ case 'c': # Final CLTV delta
            case 'n': # Node ID
                tags['payee_pubkey'] = words_to_bytes(data_words).hex()
            case 'f': # On-chain fallback address
                tags['fallback_address'] = words_to_bytes(data_words).hex()
            case 'r': # Routing hints (list of hops)
                tags['routing_hints'] = [words_to_bytes(data_words).hex()]
            # ~ case 'm': # Feature bits
            case _: # Debugging
                tags[f'unknown_{tag_char}'] = data_words

        i = data_end
    return tags

def decode_bolt11(invoice):
    hrp, data = bech32.bech32_decode(invoice.lower())
    if hrp is None or data is None:
        raise ValueError("❌ Could not decode invoice or bech32 decode failed")

    # Amount from HRP (optional)
    amount = hrp[4:] if hrp.startswith("lnbc") else "n/a"

    # Timestamp: first 7 words = 35 bits
    timestamp = from_words(data[:7])
    tag_words = data[7:-104]  # Remove timestamp and signature
    tags = parse_tags(tag_words)

    print("\n📜 Decoded BOLT11 Invoice:")
    print(f"- Prefix: {hrp}")
    print(f"- Amount (HRP): {amount}")
    # ~ print(f"- Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp))}")
    print(f"- Timestamp: {datetime.utcfromtimestamp(timestamp)}")
    print(f"- Description: {tags.get('description', 'n/a')}")
    print(f"- Payment Hash: {tags.get('payment_hash', 'n/a')}")
    print(f"- Expiry: {tags.get('expiry', '(fallback) 3600')} seconds")
    print(f"- Payee Pubkey: {tags.get('payee_pubkey', 'n/a')}")
    print(f"- Fallback Address: {tags.get('fallback_address', 'n/a')}")
    if 'routing_hints' in tags:
        print(f"- Routing Hints: {tags['routing_hints']}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Send a Lightning payment.")
    parser.add_argument("-r", "--lnaddress", help="Lightning Address")
    parser.add_argument("-a", "--amount", type=int, help="Desired amount (integer)")
    parser.add_argument("-c", "--comment", type=str, help="Optional comment to include in the invoice")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable logging")
    parser.add_argument("-f", "--logfile", type=str, help="Write log to a specified file")
    # ~ parser.add_argument("-d", "--decode", action="store_true", help="Decode and display the BOLT11 invoice")

    # Try to detect lnaddress and amount from positional args
    detected_lnaddress, detected_amount = parse_positional_args(sys.argv[1:])

    # Unpacking of parse_known_args()
    args, _ = parser.parse_known_args()

    # Logging setup
    log_handlers = []
    if args.verbose:
        log_handlers.append(logging.StreamHandler())
    if args.logfile:
        log_handlers.append(logging.FileHandler(args.logfile))

    if log_handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=log_handlers
        )
    else:
        logging.disable(logging.CRITICAL)

    # Access parsed arguments safely
    lnaddress = args.lnaddress or detected_lnaddress or input("Enter your Lightning Address: ")

    amount = args.amount or detected_amount
    # Prompt for amount only if still missing
    if amount is None:
        while True:
            user_input = input("Enter amount (integer): ")
            if user_input.isdigit():
                amount = int(user_input)
                break
            else:
                print("Amount must be a non-negative integer.")

    # Optional comment: use CLI argument or prompt user
    comment = args.comment
    if comment is None:
        comment = input("Enter a comment (optional, max length enforced by receiver, press Enter to skip): ").strip()
        if comment == "":
            comment = None

    result = get_bolt11(lnaddress, amount, comment)
    if result.get("status") == "ok":
        bolt11 = result["bolt11"]
        # ~ print(f"Generated BOLT11: ")
        print(f"{bolt11}")
    else:
        print(f"Error: {result.get('msg')}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import hashlib
import json
import logging
import argparse
import sys
import re
import urllib
from datetime import datetime

import requests
import bech32
import websocket

DEFAULT_NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
]


def is_nostr_profile(value: str) -> bool:
    """Return True for NIP-19 npub or nprofile identifiers."""
    value = normalize_nostr_uri(value).lower()
    return value.startswith("npub1") or value.startswith("nprofile1")


def is_lnurl(value: str) -> bool:
    """
    Prüft, ob der übergebene String eine LNURL ist (ggf. mit
    'lightning:'-URI-Präfix), statt einer Lightning-Adresse (name@domain.tld).
    """
    v = normalize_lightning_uri(value)
    return v.lower().startswith("lnurl1")


def normalize_nostr_uri(value: str) -> str:
    value = value.strip()

    if value.lower().startswith("nostr:"):
        value = value[len("nostr:") :].strip()

    return value


def normalize_lightning_uri(value: str) -> str:
    """
    Remove the optional 'lightning:' URI scheme prefix.

    Accepts both:
      user@domain.tld
      lightning:user@domain.tld
      lnurl1...
      lightning:lnurl1...
    """
    value = value.strip()

    if value.lower().startswith("lightning:"):
        value = value[len("lightning:") :].strip()

    return value


def decode_nostr_profile(value: str) -> tuple[str, list[str]]:
    """
    Decode a NIP-19 npub or nprofile.

    Returns:
        (pubkey_hex, relay_urls)
    """
    value = normalize_nostr_uri(value)

    hrp, data = _bech32_decode_no_limit(value)

    if hrp not in ("npub", "nprofile") or data is None:
        raise ValueError(f"Not a valid npub/nprofile: {value}")

    raw = bytes(words_to_bytes(data))

    if hrp == "npub":
        if len(raw) != 32:
            raise ValueError("Invalid npub public key length")
        return raw.hex(), []

    # NIP-19 nprofile TLV
    pubkey = None
    relays = []

    i = 0

    while i < len(raw):
        if i + 2 > len(raw):
            raise ValueError("Truncated nprofile TLV")

        tlv_type = raw[i]
        tlv_length = raw[i + 1]
        i += 2

        if i + tlv_length > len(raw):
            raise ValueError("Truncated nprofile TLV value")

        value_bytes = raw[i : i + tlv_length]
        i += tlv_length

        if tlv_type == 0:
            if len(value_bytes) != 32:
                raise ValueError("Invalid nprofile public key length")

            pubkey = value_bytes.hex()

        elif tlv_type == 1:
            try:
                relay = value_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue

            if relay.startswith(("wss://", "ws://")):
                relays.append(relay)

        # Unknown TLV types are deliberately ignored.
        # NIP-19 requires unsupported TLVs to be ignored.

    if pubkey is None:
        raise ValueError("nprofile does not contain a public key")

    return pubkey, relays


def decode_lnurl(lnurl: str) -> str:
    """
    Dekodiert eine bech32-kodierte LNURL in die zugrunde liegende HTTPS-URL.

    Akzeptiert sowohl reine LNURL-Strings (LNURL1...) als auch das
    URI-Schema 'lightning:LNURL1...'.
    """
    value = normalize_lightning_uri(lnurl)

    hrp, data = _bech32_decode_no_limit(value)

    if hrp is None or data is None:
        raise ValueError(f"Konnte LNURL nicht dekodieren (bech32-Fehler): {lnurl}")
    if hrp != "lnurl":
        raise ValueError(f"Kein LNURL-HRP gefunden (gefunden: '{hrp}'): {lnurl}")

    url_bytes = words_to_bytes(data)
    try:
        url = url_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Dekodierte LNURL-Daten sind kein gültiges UTF-8: {e}")

    logging.info("Dekodierte LNURL-URL: " + url)
    return url


def derive_lnaddress_from_url(url: str) -> str | None:
    """
    Versucht, aus einer dekodierten LNURLp-URL die zugehörige
    Lightning-Adresse (name@domain.tld) abzuleiten.

    Funktioniert nur, wenn die URL dem LUD-16-Schema
    'https://domain.tld/.well-known/lnurlp/username' entspricht.
    Andere LNURL-Formen (z. B. zufällige IDs, andere Pfade) liefern None.

    Args:
        url (str): Die dekodierte LNURL-Callback-/Metadaten-URL.

    Returns:
        str | None: Die effektive Lightning-Adresse oder None, falls
                     nicht ableitbar.
    """
    match = re.match(
        r"^https://([^/]+)/\.well-known/lnurlp/([^/?#]+)/?(?:[?#].*)?$",
        url.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None

    domain = match.group(1)
    username = match.group(2)
    return f"{username}@{domain}"


def resolve_payurl(identifier: str) -> str:
    """
    Ermittelt anhand des Eingabewerts, ob es sich um eine Lightning-Adresse
    (name@domain.tld) oder eine LNURL handelt, und liefert die passende
    HTTPS-URL für den LNURLp-Callback zurück.
    """
    if is_lnurl(identifier):
        return decode_lnurl(identifier)
    return get_payurl(identifier)


def get_nostr_profile(pubkey: str, relay_urls: list[str]) -> dict:
    """
    Retrieve the latest kind:0 profile metadata for a Nostr pubkey.
    """

    relays = relay_urls or DEFAULT_NOSTR_RELAYS

    subscription_id = "zap-profile"

    request = json.dumps([
        "REQ",
        subscription_id,
        {
            "kinds": [0],
            "authors": [pubkey],
            "limit": 1,
        },
    ], separators=(",", ":"))

    best_event = None

    for relay_url in relays:
        try:
            ws = websocket.create_connection(
                relay_url,
                timeout=5,
            )

            try:
                ws.send(request)

                while True:
                    raw = ws.recv()

                    if not raw:
                        break

                    message = json.loads(raw)

                    if not isinstance(message, list):
                        continue

                    if message[0] == "EVENT" and len(message) >= 3:
                        event = message[2]

                        if (
                            event.get("kind") == 0
                            and event.get("pubkey") == pubkey
                        ):
                            if (
                                best_event is None
                                or event.get("created_at", 0)
                                > best_event.get("created_at", 0)
                            ):
                                best_event = event

                    elif message[0] == "EOSE":
                        break

            finally:
                ws.close()

        except Exception as exc:
            logging.warning(
                "Nostr relay %s failed: %s",
                relay_url,
                exc,
            )

    if best_event is None:
        raise ValueError(
            "Nostr profile could not be found on the configured relays"
        )

    try:
        profile = json.loads(best_event.get("content", "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Nostr kind:0 profile contains invalid JSON"
        ) from exc

    if not isinstance(profile, dict):
        raise ValueError("Nostr profile metadata is not a JSON object")

    return profile


def get_profile_lnaddress(profile: dict) -> str | None:
    """
    Extract the Lightning Address from Nostr profile metadata.
    """

    lud16 = profile.get("lud16")

    if isinstance(lud16, str):
        lud16 = lud16.strip()

        if re.match(r"^[^@]+@[^@]+\.[^@]+$", lud16):
            return lud16

    # Some profiles/clients use lud06 for an LNURL.
    lud06 = profile.get("lud06")

    if isinstance(lud06, str):
        lud06 = lud06.strip()

        if is_lnurl(lud06):
            return lud06

    return None


def resolve_recipient(identifier: str) -> tuple[str, str]:
    """
    Resolve a user-entered recipient.

    Returns:
        (effective_recipient, source_type)

    source_type is one of:
        "lightning"
        "nostr"
    """

    normalized = normalize_lightning_uri(identifier)

    if is_nostr_profile(identifier):
        pubkey, relay_urls = decode_nostr_profile(identifier)

        profile = get_nostr_profile(pubkey, relay_urls)

        lnaddress = get_profile_lnaddress(profile)

        if not lnaddress:
            raise ValueError(
                "Nostr profile does not contain a Lightning Address "
                "(lud16) or LNURL (lud06)"
            )

        return lnaddress, "nostr"

    return normalized, "lightning"


def get_payurl(lnaddress):
    parts = lnaddress.split("@")
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


def verify_description_hash(datablock: dict, tags: dict) -> bool:
    metadata_raw = datablock.get("metadata", "")
    expected_hash = hashlib.sha256(metadata_raw.encode("utf-8")).hexdigest()
    return tags.get("description_hash") == expected_hash


def get_metadata_identifier(datablock: dict) -> str | None:
    """
    Extrahiert die effektive Lightning Address aus dem
    text/identifier-Eintrag des LNURLp-Metadatas.
    """
    metadata_raw = datablock.get("metadata", "[]")
    try:
        entries = json.loads(metadata_raw)
    except (json.JSONDecodeError, TypeError):
        return None

    for entry in entries:
        if (
            isinstance(entry, list)
            and len(entry) == 2
            and entry[0] == "text/identifier"
            and isinstance(entry[1], str)
            and re.match(r"^[^@]+@[^@]+\.[^@]+$", entry[1])
        ):
            return entry[1]

    return None


def get_bolt11(lnaddress, amount=None, comment=None):
    try:
        original_recipient = lnaddress

        # Resolve the entered recipient first.
        #
        # This may turn:
        #   npub1...
        #   nprofile1...
        #
        # into a Lightning Address or LNURL obtained from the Nostr profile.
        #
        # Normal Lightning Addresses and LNURLs pass through unchanged.
        lnaddress, source_type = resolve_recipient(lnaddress)

        logging.info(
            "Resolved recipient %r -> %r (%s)",
            original_recipient,
            lnaddress,
            source_type,
        )

        # Resolve the Lightning Address or LNURL to its LNURL-pay URL.
        lnaddress = normalize_lightning_uri(lnaddress)
        purl = resolve_payurl(lnaddress)

        json_content = get_url(path=purl, headers={}).strip()
        datablock = json.loads(json_content)

        description = get_metadata_description(datablock)

        logging.info(
            f"Invoice-Beschreibung (aus metadata): "
            f"{description!r} (Länge: {len(description)})"
        )

        # Validate that this is an LNURL-pay request.
        tag = datablock.get("tag")

        if tag != "payRequest":
            return {
                "status": "error",
                "msg": (
                    "Diese LNURL ist kein Pay-Request "
                    f"(gefundener Typ: '{tag}')"
                ),
            }

        # Determine the effective Lightning Address.
        #
        # Prefer:
        #   1. text/identifier from LNURL metadata
        #   2. a Lightning Address derived from the callback URL
        #   3. the resolved input itself, if it is a Lightning Address
        #
        # For Nostr recipients, lnaddress has already been replaced by the
        # Lightning Address or LNURL found in the Nostr profile.
        effective_lnaddress = (
            get_metadata_identifier(datablock)
            or derive_lnaddress_from_url(datablock.get("callback", ""))
            or (
                lnaddress
                if not is_lnurl(lnaddress)
                else None
            )
        )

        if effective_lnaddress:
            logging.info(
                "Effektive Lightning-Adresse: "
                + effective_lnaddress
            )
        else:
            logging.info(
                "Keine effektive Lightning-Adresse aus LNURL ableitbar "
                "(kein LUD-16-Schema)."
            )

        lnurlpay = datablock["callback"]
        min_amount = int(datablock["minSendable"])
        max_amount = int(datablock["maxSendable"])
        comment_allowed = int(get_comment_length(datablock))

        logging.info(
            "min. amount: " + str(min_amount)
        )

        logging.info(
            "max. amount: " + str(max_amount)
        )

        logging.info(
            "comment allowed: " + str(comment_allowed)
        )

        if amount is not None:
            amount_msat = int(amount * 1000)

            if amount_msat < min_amount:
                return {
                    "status": "error",
                    "msg": (
                        f"Amount too small, must be in range "
                        f"{min_amount // 1000} and "
                        f"{max_amount // 1000} sat"
                    ),
                    "effective_lnaddress": effective_lnaddress,
                }

            if amount_msat > max_amount:
                return {
                    "status": "error",
                    "msg": (
                        f"Amount too big, must be in range "
                        f"{min_amount // 1000} and "
                        f"{max_amount // 1000} sat"
                    ),
                    "effective_lnaddress": effective_lnaddress,
                }

        else:
            amount_msat = None

        logging.info(
            "amount: " + str(amount)
        )

        query_params = {}

        # Only include amount if one was supplied.
        if amount_msat is not None:
            query_params["amount"] = str(amount_msat)

        # Add the comment only if the receiver allows comments.
        if comment_allowed > 0 and comment:
            if len(comment) > comment_allowed:
                logging.info(
                    f"Comment truncated to "
                    f"{comment_allowed} characters"
                )

                comment = comment[:comment_allowed]

            query_params["comment"] = comment

        encoded_query = urllib.parse.urlencode(query_params)
        payquery = f"{lnurlpay}?{encoded_query}"

        logging.info(
            f"LNURL pay query: {payquery}"
        )

        ln_res = get_url(
            path=payquery,
            headers={},
        )

        pr_dict = json.loads(ln_res)

        if "pr" in pr_dict:
            return {
                "status": "ok",
                "bolt11": pr_dict["pr"],
                "effective_lnaddress": effective_lnaddress,
            }

        if "reason" in pr_dict:
            return {
                "status": "error",
                "msg": pr_dict["reason"],
                "effective_lnaddress": effective_lnaddress,
            }

        return {
            "status": "error",
            "msg": "Unexpected response format",
            "effective_lnaddress": effective_lnaddress,
        }

    except Exception as e:
        logging.error(
            "in get_bolt11: " + str(e)
        )

        return {
            "status": "error",
            "msg": str(e),
        }


def parse_positional_args(argv):
    lnaddress = None
    amount = None

    for arg in argv:
        normalized = normalize_lightning_uri(arg)

        # Detect email-like LN address
        if re.match(r"^[^@]+@[^@]+\.[^@]+$", normalized):
            lnaddress = normalized
        
        elif is_lnurl(normalized):
            lnaddress = normalized
        
        elif is_nostr_profile(arg):
            lnaddress = arg

        # Detect valid integer amount
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
        tag_char = chr(tag_int + ord("a"))

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
            case "p":  # Preimage hash (mandatory)
                tags["payment_hash"] = words_to_bytes(data_words).hex()
            case "d":  # Human-readable description (optional)
                tags["description"] = words_to_bytes(data_words).decode(
                    "utf-8", errors="ignore"
                )
            # ~ case 'h': # SHA256 hash of description (instead of d)
            # ~ tags['description_hash'] = words_to_bytes(data_words).hex()
            case "x":  # Expiry in seconds
                tags["expiry"] = from_words(data_words)
            # ~ case 'c': # Final CLTV delta
            case "n":  # Node ID
                tags["payee_pubkey"] = words_to_bytes(data_words).hex()
            case "f":  # On-chain fallback address
                tags["fallback_address"] = words_to_bytes(data_words).hex()
            case "r":  # Routing hints (list of hops)
                tags["routing_hints"] = [words_to_bytes(data_words).hex()]
            # ~ case 'm': # Feature bits
            case _:  # Debugging
                tags[f"unknown_{tag_char}"] = data_words

        i = data_end
    return tags


def get_metadata_description(datablock: dict) -> str:
    """
    Extrahiert den Klartext-Beschreibungstext aus dem metadata-Feld
    einer LNURLp-Response (vor dem BOLT11-Callback).
    """
    metadata_raw = datablock.get("metadata", "[]")
    try:
        entries = json.loads(metadata_raw)
    except (json.JSONDecodeError, TypeError):
        return ""

    for entry in entries:
        if isinstance(entry, list) and len(entry) == 2 and entry[0] == "text/plain":
            return entry[1]
    return ""


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
    if "routing_hints" in tags:
        print(f"- Routing Hints: {tags['routing_hints']}")
    print()


def _bech32_decode_no_limit(bech: str):
    """
    Wie bech32.bech32_decode(), aber ohne die interne 90-Zeichen-Begrenzung,
    da LNURLs häufig länger als 90 Zeichen sind.
    """
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return (None, None)
    if bech.lower() != bech and bech.upper() != bech:
        return (None, None)

    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        return (None, None)
    if not all(x in bech32.CHARSET for x in bech[pos + 1 :]):
        return (None, None)

    hrp = bech[:pos]
    data = [bech32.CHARSET.find(x) for x in bech[pos + 1 :]]

    if not bech32.bech32_verify_checksum(hrp, data):
        return (None, None)

    return hrp, data[:-6]  # letzte 6 Werte sind die Checksumme


def main():
    parser = argparse.ArgumentParser(description="Send a Lightning payment.")
    parser.add_argument(
        "-r",
        "--lnaddress",
        type=str,
        help="Lightning Address (name@domain.tld), LNURL (lnurl1... / lightning:lnurl1...), Nostr npub or nprofile",
    )
    parser.add_argument("-a", "--amount", type=int, help="Desired amount (integer)")
    parser.add_argument(
        "-c", "--comment", type=str, help="Optional comment to include in the invoice"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable logging")
    parser.add_argument(
        "-f", "--logfile", type=str, help="Write log to a specified file"
    )
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
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=log_handlers,
        )
    else:
        logging.disable(logging.CRITICAL)

    # Access parsed arguments safely
    lnaddress = (
        args.lnaddress or detected_lnaddress or input("Enter your Lightning Address: ")
    )

    amount = args.amount if args.amount is not None else detected_amount
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
        comment = input(
            "Enter a comment (optional, max length enforced by receiver, press Enter to skip): "
        ).strip()
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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, IPvAnyAddress
from typing import List, Optional
import ipaddress, json, os, requests, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discover-api")

NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

HEADERS = {"Authorization": f"Token {NETBOX_TOKEN}", "Content-Type": "application/json"} if NETBOX_TOKEN else {}

app = FastAPI(title="SNMP Discovery Simulator -> NetBox")

# Load simulated SNMP data file path relative to app
SIM_FILE = os.getenv("SIM_FILE", "/app/simulated_snmp_data.json")
try:
    with open(SIM_FILE, 'r') as f:
        SIM_DATA = json.load(f)
except Exception as e:
    logger.error("Could not load simulated SNMP file: %s", e)
    SIM_DATA = {}

class DiscoverRequest(BaseModel):
    ips: Optional[List[IPvAnyAddress]] = Field(None, description="Explicit list of IPs to scan")
    cidr: Optional[str] = Field(None, description="CIDR range to scan, e.g. 192.168.1.0/29")
    name_prefix: Optional[str] = Field(None, description="Optional name prefix for created devices")

    class Config:
        schema_extra = {
            "example": {"cidr": "192.168.1.0/29"}
        }

def expand_targets(req: DiscoverRequest):
    targets = set()
    if req.ips:
        targets |= {str(ip) for ip in req.ips}
    if req.cidr:
        try:
            net = ipaddress.ip_network(req.cidr, strict=False)
            for ip in net.hosts():
                targets.add(str(ip))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid CIDR: {e}")
    if not targets:
        raise HTTPException(status_code=400, detail="No targets provided (ips or cidr).")
    return sorted(targets)

# Simple NetBox wrapper functions (minimal)
def netbox_get(path, params=None):
    if not NETBOX_URL or not NETBOX_TOKEN:
        logger.info("NETBOX not configured, skipping GET %s", path)
        return None
    url = NETBOX_URL.rstrip('/') + path
    r = requests.get(url, headers=HEADERS, params=params, timeout=10)
    if r.status_code in (200, 201):
        return r.json()
    logger.error("NetBox GET %s returned %s: %s", url, r.status_code, r.text)
    raise Exception(f"NetBox error GET {r.status_code}")

def netbox_post(path, payload):
    if not NETBOX_URL or not NETBOX_TOKEN:
        logger.info("NETBOX not configured, skipping POST %s payload=%s", path, payload)
        return None
    url = NETBOX_URL.rstrip('/') + path
    r = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    if r.status_code in (200,201):
        return r.json()
    logger.error("NetBox POST %s returned %s: %s", url, r.status_code, r.text)
    raise Exception(f"NetBox error POST {r.status_code} {r.text}")

def netbox_patch(path, payload):
    if not NETBOX_URL or not NETBOX_TOKEN:
        logger.info("NETBOX not configured, skipping PATCH %s payload=%s", path, payload)
        return None
    url = NETBOX_URL.rstrip('/') + path
    r = requests.patch(url, headers=HEADERS, json=payload, timeout=10)
    if r.status_code in (200,201):
        return r.json()
    logger.error("NetBox PATCH %s returned %s: %s", url, r.status_code, r.text)
    raise Exception(f"NetBox error PATCH {r.status_code} {r.text}")

def find_device_by_name(name):
    if not NETBOX_URL or not NETBOX_TOKEN:
        return None
    res = netbox_get("/api/dcim/devices/", params={"name": name})
    if res and res.get("count",0) > 0:
        return res["results"][0]
    return None

def create_device(nb_payload):
    return netbox_post("/api/dcim/devices/", nb_payload)

def update_device(device_id, payload):
    return netbox_patch(f"/api/dcim/devices/{device_id}/", payload)

def create_interface(payload):
    return netbox_post("/api/dcim/interfaces/", payload)

def create_ip(payload):
    return netbox_post("/api/ipam/ip-addresses/", payload)

def ip_with_prefix(ip, netmask):
    try:
        # Convert netmask to prefix length
        pref = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False).prefixlen
        return f"{ip}/{pref}"
    except Exception:
        return f"{ip}/32"

@app.post("/api/v/discover")
def discover(req: DiscoverRequest):
    targets = expand_targets(req)
    results = {"scanned": [], "created": [], "updated": [], "skipped": [], "errors": []}
    for ip in targets:
        results["scanned"].append(ip)
        data = SIM_DATA.get(ip)
        if not data:
            results["skipped"].append({"ip": ip, "reason": "no simulated SNMP data"})
            continue

        device_name = data.get("sysName") or f"device-{ip}"
        nb_device = None
        try:
            existing = find_device_by_name(device_name)
        except Exception as e:
            results["errors"].append({"ip": ip, "error": str(e)})
            continue

        nb_payload = {
            "name": device_name,
            "device_type": None,
            "device_role": None,
            "serial": None,
            "site": None,
            "status": "active",
            "comments": f"Discovered via simulated SNMP. sysDescr: {data.get('sysDescr')}"
        }

        try:
            if existing:
                # Update device (example: update comments)
                update_device(existing["id"], {"comments": nb_payload["comments"]})
                results["updated"].append({"ip": ip, "device": device_name})
                nb_device = existing
            else:
                created = create_device(nb_payload)
                results["created"].append({"ip": ip, "device": device_name})
                nb_device = created
        except Exception as e:
            # NetBox may not be configured — just record
            results["errors"].append({"ip": ip, "error": str(e)})
            nb_device = None

        # Create interfaces and IPs
        interfaces = data.get("interfaces", [])
        for iface in interfaces:
            if_descr = iface.get("ifDescr") or f"if{iface.get('ifIndex')}"
            iface_payload = {
                "device": nb_device["id"] if nb_device and isinstance(nb_device, dict) and nb_device.get("id") else None,
                "name": if_descr,
                "type": "1000base-t" if iface.get("ifSpeed",0) >= 1000000000 else "other",
                "enabled": True if iface.get("ifAdminStatus") == 1 else False,
                "mac_address": iface.get("ifPhysAddress")
            }
            try:
                created_iface = create_interface(iface_payload) if iface_payload["device"] else None
            except Exception as e:
                results["errors"].append({"ip": ip, "iface": if_descr, "error": str(e)})
                created_iface = None

            ipaddr = iface.get("ipAddress")
            netmask = iface.get("ipNetmask")
            if ipaddr and netmask:
                ip_payload = {
                    "address": ip_with_prefix(ipaddr, netmask),
                    "status": "active",
                    "description": f"Auto-discovered on {device_name} {if_descr}",
                    # Optional: assign to interface when available
                    "assigned_object_type": "dcim.interface",
                    # NetBox expects 'assigned_object_id' when assigning; we'll leave null if no interface created
                    "assigned_object_id": created_iface["id"] if created_iface and created_iface.get("id") else None
                }
                try:
                    created_ip = create_ip(ip_payload)
                except Exception as e:
                    results["errors"].append({"ip": ip, "iface": if_descr, "ip": ipaddr, "error": str(e)})
        # Done with device
    return results

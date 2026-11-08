from fastapi import FastAPI
from pydantic import BaseModel
from netmiko import ConnectHandler
from enum import Enum
import subprocess
import os
import json

app = FastAPI(
    title="SDN Hálózatvezérlő Központ",
    description="Szakdolgozat API a Kathará hálózat automatizálásához",
    version="1.0.0"
)

ROUTER_IP = "127.0.0.1"

router_device = {
    "device_type": "linux",
    "host": ROUTER_IP,
    "username": "root",
    "password": "admin",
    "port": 2222,
}

network_state = {
    "vlans": [],
    "firewall_rules": [],
    "qos_rules": []
}

class ConnectRangeRequest(BaseModel):
    prefix: str        # Például: "pc"
    start_num: int     # Például: 1
    end_num: int       # Például: 10
    vlan_id: int       # Például: 10

class SaveConfigRequest(BaseModel):
    config_name: str

class LoadConfigRequest(BaseModel):
    config_name: str

class PcConfig(BaseModel):
    pc_name: str
    vlan_id: int

class QosConfig(BaseModel):
    vlan_id: int
    rate_limit: str  # pl. "1mbit" vagy "500kbit"

class AclAction(str, Enum):
    permit = "permit"
    deny = "deny"

class FirewallConfig(BaseModel):
    source_vlan: int
    destination_vlan: int
    action: AclAction

class RouterConfig(BaseModel):
    ip_address: str
    subnet_mask: str

class VlanConfig(BaseModel):
    vlan_id: int
    ip_address: str
    subnet_mask: str

class DhcpConfig(BaseModel):
    vlan_id: int
    range_start: str
    range_end: str

@app.get("/")
def home():
    return {"status": "Online", "message": "Az SDN Controller sikeresen fut!"}

@app.get("/router-status")
def get_router_status():
    try:
        net_connect = ConnectHandler(**router_device)
        output = net_connect.send_command("vtysh -c 'show interface brief'")
        net_connect.disconnect()
        return {"router": "r1", "connection": "Success", "interfaces": output}
    except Exception as e:
        return {"router": "r1", "connection": "Failed", "error": str(e)}

@app.post("/configure-router")
def configure_router(config: RouterConfig):
    try:
        net_connect = ConnectHandler(**router_device)
        commands = [
            f"ip addr add {config.ip_address}/{config.subnet_mask} dev eth0",
            "ip link set eth0 up"
        ]
        output = net_connect.send_config_set(commands)
        net_connect.disconnect()
        return {"status": "Configuration Applied", "details": output}
    except Exception as e:
        return {"status": "Configuration Failed", "error": str(e)}

@app.post("/configure-vlan")
def configure_vlan(config: VlanConfig):
    try:
        net_connect = ConnectHandler(**router_device)
        commands = [
            "ip link set eth0 up",
            f"ip link add link eth0 name eth0.{config.vlan_id} type vlan id {config.vlan_id}",
            f"ip addr add {config.ip_address}/{config.subnet_mask} dev eth0.{config.vlan_id}",
            f"ip link set eth0.{config.vlan_id} up"
        ]
        output = net_connect.send_config_set(commands)
        net_connect.disconnect()

        # --- A network_state frissítése ---
        # Hozzáteszünk egy új VLAN-t a későbbi betöltéshez szükséges mezőkkel
        network_state["vlans"].append({
            "vlan_id": config.vlan_id,
            "ip_address": config.ip_address,
            "subnet_mask": config.subnet_mask,
            "dhcp_start": "",    # ezt később a /configure-dhcp parancs tölti ki
            "dhcp_end": ""
        })

        return {
            "router": "r1",
            "status": "VLAN Successfully Created",
            "vlan_id": config.vlan_id,
            "ip_assigned": config.ip_address,
            "details": output
        }
    except Exception as e:
        return {
            "router": "r1",
            "status": "VLAN Configuration Failed",
            "error": str(e)
        }

@app.post("/configure-dhcp")
def configure_dhcp(config: DhcpConfig):
    try:
        net_connect = ConnectHandler(**router_device)
        command = f"pkill dnsmasq; dnsmasq --interface=eth0.{config.vlan_id} --dhcp-range={config.range_start},{config.range_end},12h"
        output = net_connect.send_command(command)
        net_connect.disconnect()

        # --- A network_state frissítése ---
        # Megkeressük a VLAN-t a listában
        found = False
        for vlan in network_state["vlans"]:
            if vlan["vlan_id"] == config.vlan_id:
                vlan["dhcp_start"] = config.range_start
                vlan["dhcp_end"] = config.range_end
                found = True
                break
        if not found:
            # Ha a VLAN még nincs regisztrálva (például manuálisan konfigurálták),
            # akkor vagy üres mezőkkel létrehozhatjuk, vagy hibaüzenetet adhatunk ki.
            # Ebben az esetben hibaüzenetet adunk ki, hogy kikényszerítsük a műveletek sorrendjét.
            return {
                "router": "r1",
                "status": "DHCP Configuration Failed",
                "error": f"VLAN {config.vlan_id} not found in network_state. Please configure VLAN first."
            }

        return {
            "router": "r1",
            "status": "DHCP Server Started",
            "vlan_id": config.vlan_id,
            "dhcp_pool": f"{config.range_start} - {config.range_end}",
            "details": output
        }
    except Exception as e:
        return {
            "router": "r1",
            "status": "DHCP Configuration Failed",
            "error": str(e)
        }

@app.delete("/remove-vlan/{vlan_id}")
def remove_vlan(vlan_id: int):
    try:
        net_connect = ConnectHandler(**router_device)
        
        # 1. Célzottan kilőjük a DHCP szervert, ami ezen a VLAN-on fut
        net_connect.send_command(f"pkill -f 'eth0.{vlan_id}'")
        
        # 2. Lekapcsoljuk és töröljük a virtuális VLAN kábelt a routerről
        commands = [
            f"ip link set eth0.{vlan_id} down",
            f"ip link delete eth0.{vlan_id}"
        ]
        output = net_connect.send_config_set(commands)
        net_connect.disconnect()
        
        return {
            "router": "r1",
            "status": "VLAN and DHCP Successfully Removed",
            "vlan_id": vlan_id,
            "details": output
        }
    except Exception as e:
        return {
            "router": "r1",
            "status": "Removal Failed",
            "error": str(e)
        }

@app.post("/configure-firewall")
def configure_firewall(config: FirewallConfig):
    try:
        net_connect = ConnectHandler(**router_device)
        target = "ACCEPT" if config.action == AclAction.permit else "DROP"
        command = f"iptables -I FORWARD 1 -i eth0.{config.source_vlan} -o eth0.{config.destination_vlan} -j {target}"
        output = net_connect.send_command(command)
        net_connect.disconnect()

        # --- A network_state frissítése ---
        network_state["firewall_rules"].append({
            "source_vlan": config.source_vlan,
            "destination_vlan": config.destination_vlan,
            "action": config.action.value  # "permit" ou "deny"
        })

        return {
            "router": "r1",
            "status": "Firewall Rule Applied",
            "rule": f"VLAN {config.source_vlan} -> VLAN {config.destination_vlan} : {target}",
            "details": output
        }
    except Exception as e:
        return {
            "router": "r1",
            "status": "Firewall Configuration Failed",
            "error": str(e)
        }
    
@app.post("/configure-qos")
def configure_qos(config: QosConfig):
    try:
        net_connect = ConnectHandler(**router_device)
        net_connect.send_command(f"tc qdisc del dev eth0.{config.vlan_id} root")
        command = f"tc qdisc add dev eth0.{config.vlan_id} root tbf rate {config.rate_limit} burst 32kbit latency 400ms"
        output = net_connect.send_command(command)
        net_connect.disconnect()

        # --- A network_state frissítése---
        network_state["qos_rules"].append({
            "vlan_id": config.vlan_id,
            "rate_limit": config.rate_limit
        })

        return {
            "router": "r1",
            "status": "QoS Rule Applied",
            "vlan_id": config.vlan_id,
            "rate_limit": config.rate_limit,
            "details": output
        }
    except Exception as e:
        return {
            "router": "r1",
            "status": "QoS Configuration Failed",
            "error": str(e)
        }

@app.post("/connect-pc")
def connect_pc(config: PcConfig):
    try:
        commands = (
            f"ip link add link eth0 name eth0.{config.vlan_id} type vlan id {config.vlan_id} && "
            "ip link set eth0 up && "
            f"ip link set eth0.{config.vlan_id} up && "
            f"dhclient -v eth0.{config.vlan_id}"
        )
        
        # JAVÍTVA: Közvetlen Docker helyett a Katharára bízzuk a futtatást!
        result = subprocess.run(
            ["kathara", "exec", config.pc_name, "--", "bash", "-c", commands],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return {
                "pc": config.pc_name,
                "status": "Successfully Connected and IP Acquired",
                "details": result.stdout
            }
        else:
            return {
                "pc": config.pc_name,
                "status": "Connection Failed",
                "error": result.stderr
            }
    except Exception as e:
        return {
            "pc": config.pc_name,
            "status": "Automation Error",
            "error": str(e)
        }
@app.post("/save-config")
def save_config(data: SaveConfigRequest):
    try:
        os.makedirs("configs", exist_ok=True)
        file_path = os.path.join("configs", f"{data.config_name}.json")
        
        # A memóriában lévő aktuális állapotot mentjük ki automatikusan
        with open(file_path, "w") as f:
            json.dump(network_state, f, indent=4)
            
        return {
            "status": "Current Network State Saved Successfully!",
            "saved_file": file_path,
            "saved_data": network_state
        }
    except Exception as e:
        return {
            "status": "Save Failed",
            "error": str(e)
        }

@app.post("/load-config")
def load_config(data: LoadConfigRequest):
    try:
        file_path = os.path.join("configs", f"{data.config_name}.json")
        if not os.path.exists(file_path):
            return {
                "status": "Load Failed",
                "error": f"Configuration '{data.config_name}' does not exist."
            }
            
        with open(file_path, "r") as f:
            saved_config = json.load(f)
            
        # Frissítjük a globális memóriát a betöltött adatokra
        global network_state
        network_state = saved_config
        
        net_connect = ConnectHandler(**router_device)
        results = []
        
        # 1. VLAN-ok és DHCP visszaállítása a fájrból
        for vlan in saved_config.get("vlans", []):
            v_id = vlan["vlan_id"]
            ip = vlan["ip_address"]
            mask = vlan["subnet_mask"]
            start = vlan["dhcp_start"]
            end = vlan["dhcp_end"]
            
            commands = [
                f"interface eth0.{v_id}",
                f"ip address {ip}/{mask}",
                "no shutdown"
            ]
            net_connect.send_config_set(commands)
            net_connect.send_command(f"pkill -f 'eth0.{v_id}'")
            net_connect.send_command(f"dnsmasq --interface=eth0.{v_id} --dhcp-range={start},{end},12h")
            results.append(f"VLAN {v_id} & DHCP restored.")

        # 2. Tűzfalszabályok (ACL) visszaállítása
        for rule in saved_config.get("firewall_rules", []):
            src = rule["source_vlan"]
            dst = rule["destination_vlan"]
            action = rule["action"]
            cmd = f"iptables -I FORWARD 1 -i eth0.{src} -o eth0.{dst} -j {action}"
            net_connect.send_command(cmd)
            results.append(f"Firewall rule restored: VLAN {src} -> VLAN {dst} [{action}]")

        # 3. QoS (Sávszélesség) visszaállítása
        for qos in saved_config.get("qos_rules", []):
            v_id = qos["vlan_id"]
            rate = qos["rate_limit"]
            net_connect.send_command(f"tc qdisc del dev eth0.{v_id} root 2>/dev/null")
            cmd = f"tc qdisc add dev eth0.{v_id} root tbf rate {rate} burst 32kbit latency 400ms"
            net_connect.send_command(cmd)
            results.append(f"QoS restored on VLAN {v_id}: limit {rate}")
            
        net_connect.disconnect()
        return {
            "status": f"Configuration '{data.config_name}' Loaded and Applied Successfully!",
            "details": results
        }
    except Exception as e:
        return {
            "status": "Load Failed",
            "error": str(e)
        }
@app.post("/connect-pc-range")
def connect_pc_range(data: ConnectRangeRequest):
    try:
        net_connect = ConnectHandler(**router_device)
        results = []
        
        # Ciklus az intervallumon (pl. pc1-től pc10-ig)
        for i in range(data.start_num, data.end_num + 1):
            pc_name = f"{data.prefix}{i}"
            
            # Parancsok küldése a Kathara gépek hálózati beállításához
            # (Például a gép felélesztése és DHCP kérés indítása)
            commands = [
                f"docker exec -d {pc_name} ip link set eth0 up",
                f"docker exec -d {pc_name} dhclient eth0"
            ]
            
            for cmd in commands:
                net_connect.send_command(cmd)
                
            results.append(f"PC '{pc_name}' connected to VLAN {data.vlan_id} successfully.")
            
        net_connect.disconnect()
        return {
            "status": f"Successfully connected range {data.prefix}{data.start_num}-{data.prefix}{data.end_num}!",
            "details": results
        }
    except Exception as e:
        return {
            "status": "Range Connection Failed",
            "error": str(e)
        }
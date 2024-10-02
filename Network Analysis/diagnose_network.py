#!/usr/bin/env python3

# -------------------------------------------------------
# Script: diagnose_network.py
#
# Description:
# This script provides comprehensive network diagnostics to
# automatically troubleshoot network issues.
# It includes functionalities such as system information gathering, device discovery,
# automated diagnostics, advanced network traffic monitoring, and WiFi analysis.
#
# Usage:
# ./diagnose_network.py [command] [options]
#
# Commands:
# - system-info (si)          Display detailed network information about the system.
# - diagnose (dg)             Perform automated diagnostics on the network.
# - traffic-monitor (tm)      Monitor network traffic to detect anomalies using Scapy.
# - wifi (wf)                 Perform WiFi diagnostics and analyze available networks.
# - container (co)            Run the script inside of a Docker container.
#
# Global Options:
# -v, --verbose               Enable verbose logging (INFO level).
# -vv, --debug                Enable debug logging (DEBUG level).
#
# System Info Command Options:
# -t, --traceroute            Perform a traceroute to a specified address (default: 8.8.8.8, 2001:4860:4860::8888).
#
# Diagnostics Command Options:
# -V, --virtual               Enable virtual interfaces in network scanning.
# -6, --ipv6                  Enable IPv6 in network scanning.
# -d, --discovery             Perform network discovery to find devices only.
# -o, --output-file           Specify a file to save discovered devices.
# -i, --input-file            Specify a file to load discovered devices.
# -e, --execution             Specify the execution mode (choices: docker, native) (default: docker).
# -N, --nikto                 Enable Nikto scanning for discovered devices.
# -G, --golismero             Enable Golismero automated scanning for discovered devices.
# -C, --credentials           Enable default credentials check for discovered devices.
# -A, --all                   Enable all available diagnostic tools.
#
# Traffic Monitor Command Options:
# -i, --interface             Specify the network interface to monitor (e.g., wlan0, eth0).
# --dhcp-threshold            Set DHCP flood threshold (default: 100).
# --port-scan-threshold       Set port scan threshold (default: 50).
# --dns-exfil-threshold       Set DNS exfiltration threshold (default: 1000).
# --bandwidth-threshold       Set bandwidth abuse threshold in bytes per minute (default: 1000000).
# --icmp-threshold            Set ICMP flood threshold (default: 500).
# --syn-threshold             Set SYN flood threshold (default: 1000).
# --http-threshold            Set HTTP abuse threshold (default: 1000).
# --malformed-threshold       Set malformed packets threshold (default: 50).
# --rogue-dhcp-threshold      Set rogue DHCP server threshold (default: 1).
#
# WiFi Command Options:
# -s, --ssid                  Specify the SSID to perform targeted diagnostics.
#                             If not specified, performs generic WiFi checks.
# -i, --interface             Specify the network interface to scan (e.g., wlan0, wlp3s0).
# -m, --signal-threshold      Set the minimum signal strength threshold (default: 50).
#
# Container Command Options:
# -n, --network               Docker network mode to use (choices: bridge, host, macvlan, default) (default: host).
# -w, --work-dir              Specify the working directory to mount into the container (default: working directory).
# --                          Pass additional arguments to the script inside the container.
#
# Returns:
# Exit code 0 on success, non-zero on failure.
#
# Requirements with container:
# - Python3
# - Docker (install via: apt install docker.io)
# - psutil (optional, for macvlan) (install via: apt install python3-psutil)
#
# Requirements without container:
# - System Info Command:
#   - traceroute (install via: apt install traceroute)
#
# - Diagnose Command:
#   - requests (install via: pip install requests)
#   - nmap (install via: apt install nmap)
#   - docker (install via: apt install docker.io)
#   - Nikto Check (native):
#     - nikto (install via: apt install nikto)
#   - Golismero Check (native):
#     - golismero (install via: pip install golismero)
#   - Credentials Check:
#     - BeautifulSoup (install via: pip install beautifulsoup4)
#
# - Traffic Monitor Command:
#   - scapy (install via: pip install scapy)
#
# - WiFi Command:
#   - nmcli (install via: apt install network-manager)
#
# Optional:
# - rich (install via: pip install rich)
# - python-dotenv (install via: pip install python-dotenv)
#
# -------------------------------------------------------
# © 2024 Hendrik Buchwald. All rights reserved.
# -------------------------------------------------------

import argparse
import logging
import os
import sys
import subprocess
import socket
import struct
import json
import time
import threading
import queue
import shutil
import re
import tempfile
import ipaddress
from urllib.parse import urlparse
from enum import Enum
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Set, Tuple, Any, TypeVar, Type, Union, get_origin, get_args
from collections import defaultdict, deque
from datetime import datetime, timedelta
from dataclasses import asdict, dataclass, field, is_dataclass, fields
import xml.etree.ElementTree as ET

# Ignore unnecessary warnings
import warnings
from urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

# Load environment variables from a .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Attempt to import rich for enhanced terminal outputs
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.panel import Panel
    from rich.logging import RichHandler
    RICH_AVAILABLE = True
except ImportError:
    Console = None
    RICH_AVAILABLE = False

# Attempt to import scapy for advanced network monitoring
try:
    from scapy.all import sniff, ARP, DHCP, IP, TCP, UDP, ICMP, DNS, DNSQR, Ether, Raw
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

# Attempt to import requests for HTTP requests
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Attempt to import BeautifulSoup for HTML parsing
try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BEAUTIFULSOUP_AVAILABLE = False

# Attempt to import psutil for system information
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

# Initialize Rich console if available
console = Console() if RICH_AVAILABLE else None


# Constants
class ExecutionMode(str, Enum):
    DOCKER = 'docker'
    NATIVE = 'native'


# Issue data classes
@dataclass
class DiagnoseIssue:
    device_type: str
    hostname: str
    ip: str
    port: int
    product: str
    description: str


@dataclass
class WifiIssue:
    issue_type: str
    location: str
    description: str


# Configuration data classes
@dataclass
class CredentialsConfig:
    """
    Configuration for default credentials, organized by vendor and generic credentials.
    """
    vendor_credentials: Dict[str, List[Dict[str, str]]] = field(default_factory=lambda: {
        "cisco": [
            {"username": "admin", "password": "admin"},
            {"username": "cisco", "password": "cisco"},
            {"username": "support", "password": "support"},
        ],
        "dlink": [
            {"username": "admin", "password": "admin"},
            {"username": "admin", "password": "password"},
            {"username": "user", "password": "user"},
        ],
        "netgear": [
            {"username": "admin", "password": "password"},
            {"username": "admin", "password": "netgear"},
            {"username": "admin", "password": "1234"},
        ],
        "tplink": [
            {"username": "admin", "password": "admin"},
            {"username": "user", "password": "user"},
            {"username": "admin", "password": "password"},
        ],
        "huawei": [
            {"username": "admin", "password": "admin"},
            {"username": "root", "password": "root"},
            {"username": "huawei", "password": "huawei"},
        ],
        "asus": [
            {"username": "admin", "password": "admin"},
            {"username": "admin", "password": "asus"},
        ],
        "linksys": [
            {"username": "admin", "password": "admin"},
            {"username": "admin", "password": "linksys"},
        ],
        "zyxel": [
            {"username": "admin", "password": "1234"},
            {"username": "admin", "password": "admin"},
        ],
        "mikrotik": [
            {"username": "admin", "password": ""},
            {"username": "admin", "password": "admin"},
        ],
        "belkin": [
            {"username": "admin", "password": "password"},
            {"username": "admin", "password": "admin"},
        ],
        # Add more vendors as needed
    })
    generic_credentials: List[Dict[str, str]] = field(default_factory=lambda: [
        {"username": "admin", "password": "admin"},
        {"username": "admin", "password": "password"},
        {"username": "root", "password": "root"},
        {"username": "user", "password": "user"},
        {"username": "guest", "password": "guest"},
        {"username": "admin", "password": "1234"},
        {"username": "admin", "password": "password123"},
        {"username": "admin", "password": "default"},
        {"username": "admin", "password": "letmein"},
        {"username": "admin", "password": "admin123"},
        # Add more generic credentials as needed
    ])

    def get_vendor_credentials(self, vendor: str) -> List[Dict[str, str]]:
        """
        Retrieve vendor-specific credentials based on the vendor string.
        Combines with generic credentials, avoiding duplicates.
        """
        credentials = []
        for vendor_substr, creds in self.vendor_credentials.items():
            if vendor_substr.lower() in vendor.lower():
                credentials.extend(creds)

        if credentials:
            # Combine with generic_credentials, avoiding duplicates
            seen = set()
            unique_credentials = []
            for cred in credentials:
                key = (cred['username'], cred['password'])
                if key not in seen:
                    unique_credentials.append(cred)
                    seen.add(key)
            for cred in self.generic_credentials:
                key = (cred['username'], cred['password'])
                if key not in seen:
                    unique_credentials.append(cred)
                    seen.add(key)
            return unique_credentials
        else:
            return self.generic_credentials


@dataclass
class EndpointsConfig:
    common_sensitive_endpoints: Set[str] = field(default_factory=lambda: {
        "/backup",
        "/diag.html",
        "/status",
        "/advanced",
        "/system",
        "/tools",
        "/filemanager",
        "/download",
        "/logs",
        "/debug",
    })
    vendor_additional_sensitive_endpoints: Dict[str, Set[str]] = field(default_factory=lambda: {
        'fritz!box': {
            "/admin/config.php",
            "/diag_wps.html",
        },
        'asus': {
            "/admin/config.php",
        },
        'netgear': {
            "/cgi-bin/fwupdate",
            "/status/wps",
        },
        'tp-link': set(),
        'd-link': {
            "/status.html",
        },
        'linksys': {
            "/status.html",
        },
        'belkin': {
            "/cgi-bin/admin/config",
            "/status.cgi",
        },
        'synology': {
            "/webman/index.cgi",
            "/status.cgi",
        },
        'ubiquiti': {
            "/cgi-bin/status.cgi",
        },
        'mikrotik': {
            "/login",
        },
        'zyxel': {
            "/cgi-bin/admin/config",
        },
        'huawei': {
            "/cgi-bin/hwcfg.cgi",
        },
        'apple': {
            "/airport/admin",
        },
    })

    def get_vendor_config(self, vendor: str) -> Dict[str, Set[str]]:
        # Collect all additional sensitive endpoints where the key is a substring of the vendor
        additional_sensitive = set()
        for key, endpoints in self.vendor_additional_sensitive_endpoints.items():
            if key.lower() in vendor.lower():
                additional_sensitive.update(endpoints)

        return {
            'sensitive_endpoints': self.common_sensitive_endpoints.union(additional_sensitive)
        }


@dataclass
class HttpSecurityConfig:
    """
    Configuration for HTTP security headers.
    """
    security_headers: Set[str] = field(default_factory=lambda: {
        'Content-Security-Policy',
        'Strict-Transport-Security',
        'X-Frame-Options',
        'X-Content-Type-Options',
        'Referrer-Policy',
        'Feature-Policy',
        'Permissions-Policy'
    })


@dataclass
class GamingServicesConfig:
    """
    Configuration for gaming-specific services per vendor.
    Maps vendor names to their associated gaming services and ports.
    """
    gaming_services: Dict[str, Dict[int, str]] = field(default_factory=lambda: {
        'sony': {
            3075: "PlayStation Network",
            3076: "PlayStation Network"
        },
        'microsoft': {
            3074: "Xbox Live",
            # Add more ports and services as needed
        },
        'nintendo': {
            6667: "Nintendo Switch",
            12400: "Nintendo Switch"
        },
        # Add additional vendors and their gaming services here
    })


@dataclass
class DeviceAddress:
    address: str
    address_type: str
    vendor: Optional[str] = None


@dataclass
class DeviceServiceScript:
    script_id: str
    output: str


@dataclass
class DeviceService:
    confidence: Optional[str]
    method: Optional[str]
    name: Optional[str]
    product: Optional[str]
    version: Optional[str]
    service_fingerprint: Optional[str]
    cpe_list: List[str] = field(default_factory=list)
    scripts: List[DeviceServiceScript] = field(default_factory=list)


@dataclass
class DevicePort:
    port_id: int
    protocol: str
    state: str
    reason: Optional[str] = None
    service: Optional[DeviceService] = None


@dataclass
class DeviceOsMatch:
    accuracy: int
    name: str
    os_family: Optional[str] = None
    os_gen: Optional[str] = None
    os_type: Optional[str] = None
    vendor: Optional[str] = None
    cpe_list: List[str] = field(default_factory=list)
    ports_used: List[str] = field(default_factory=list)


@dataclass
class DeviceOs:
    os_matches: List[DeviceOsMatch] = field(default_factory=list)
    ports_used: List[str] = field(default_factory=list)  # Simplified as list of strings


@dataclass
class DeviceTraceHop:
    host: Optional[str]
    ip_address: Optional[str]
    round_trip_time: Optional[float]
    time_to_live: Optional[int]


@dataclass
class DeviceTrace:
    hops: List[DeviceTraceHop] = field(default_factory=list)


@dataclass
class DeviceUptime:
    last_boot_time: str
    uptime_seconds: int


@dataclass
class Device:
    ip_addresses: List[str] = field(default_factory=list)
    mac_address: Optional[str] = None
    vendor: Optional[str] = None
    hostnames: List[str] = field(default_factory=list)
    operating_system: Optional[str] = None
    os_matches: List[DeviceOsMatch] = field(default_factory=list)
    ports: List[DevicePort] = field(default_factory=list)
    uptime: Optional[DeviceUptime] = None
    distance: Optional[int] = None
    trace: Optional[DeviceTrace] = None
    rtt_variance: Optional[int] = None
    smoothed_rtt: Optional[int] = None
    timeout: Optional[int] = None
    os_info: Optional[DeviceOs] = None


@dataclass
class DeviceType:
    """
    Represents a type of network device with specific identification criteria.
    """
    name: str
    vendors: Set[str] = field(default_factory=set)
    ports: Set[str] = field(default_factory=set)
    os_keywords: Set[str] = field(default_factory=set)
    priority: int = 0  # Lower number means higher priority

    def matches(self, device: Device) -> bool:
        """
        Determines if a given device matches the criteria of this device type.
        """
        # Construct the set of port descriptions as "port_id/protocol"
        device_ports = set()
        for port in device.ports:
            if port.state == 'open' and port.service:
                port_desc = f"{port.port_id}/{port.protocol.lower()}"
                device_ports.add(port_desc)

        # Extract and process OS information
        os_info = device.operating_system.lower() if device.operating_system else ""

        # Extract and process vendor information
        vendor = device.vendor.lower() if device.vendor else "unknown"

        # Find matches based on DeviceTypeConfig requirements
        vendor_match = any(v in vendor for v in self.vendors)
        ports_match = bool(self.ports.intersection(device_ports))
        os_match = any(keyword in os_info for keyword in self.os_keywords) if self.os_keywords else False

        # Combine conditions based on device type requirements
        if self.name == "Phone":
            return vendor_match or ports_match
        elif self.name == "Smart":
            return vendor_match or os_match
        elif self.name == "Game":
            return (vendor_match or os_match) and ports_match
        elif self.name == "Computer":
            return os_match or bool(device_ports)

        # Default condition: require both vendor and ports to match
        return vendor_match and ports_match


@dataclass
class DeviceTypeConfig:
    """
    Configuration for various device types used in the network.
    Contains a list of DeviceType instances, each defining criteria for a specific type of device.
    """
    device_types: List[DeviceType] = field(default_factory=lambda: [
        DeviceType(
            name="Router",
            vendors={'fritz!box', 'asus', 'netgear', 'tp-link', 'd-link', 'linksys', 'belkin', 'synology', 'ubiquiti', 'mikrotik', 'zyxel'},
            ports={'80/tcp', '443/tcp', '23/tcp', '22/tcp'},
            priority=1
        ),
        DeviceType(
            name="Switch",
            vendors={'cisco', 'hp', 'd-link', 'netgear', 'ubiquiti', 'juniper', 'huawei'},
            ports={'22/tcp', '23/tcp', '161/udp', '161/tcp'},
            priority=2
        ),
        DeviceType(
            name="Printer",
            vendors={'hp', 'canon', 'epson', 'brother', 'lexmark', 'samsung', 'xerox', 'lightspeed'},
            ports={'9100/tcp', '515/tcp', '631/tcp'},
            priority=3
        ),
        DeviceType(
            name="Phone",
            vendors={'cisco', 'yealink', 'polycom', 'avaya', 'grandstream'},
            ports={'5060/tcp', '5060/udp'},
            priority=4
        ),
        DeviceType(
            name="Smart",
            vendors={'google', 'amazon', 'ring', 'nest', 'philips', 'samsung', 'lg', 'lifi labs', 'roborock', 'harman'},
            os_keywords={'smart', 'iot', 'camera', 'thermostat', 'light', 'sensor', 'hub'},
            priority=5
        ),
        DeviceType(
            name="Game",
            vendors={'sony', 'microsoft', 'nintendo'},
            ports={'3074/tcp', '3074/udp', '3075/tcp', '3075/udp', '3076/tcp', '3076/udp'},
            priority=6
        ),
        DeviceType(
            name="Computer",
            ports={'22/tcp', '139/tcp', '445/tcp', '3389/tcp', '5900/tcp'},
            os_keywords={'windows', 'macos', 'linux'},
            priority=7
        ),
    ])


@dataclass
class DockerConfig:
    """
    Configuration for Docker-specifics.
    """
    images: Dict[str, str] = field(default_factory=lambda: {
        'nmap': 'instrumentisto/nmap:7',  # Currently unused
        'nikto': 'alpine/nikto:2.2.0',
        'golismero': 'jsitech/golismero'
    })


@dataclass
class AppConfig:
    """
    Comprehensive application configuration encompassing credentials, endpoints, device types,
    HTTP security settings, gaming services, SNMP communities, and more.
    """
    credentials: CredentialsConfig = field(default_factory=CredentialsConfig)
    endpoints: EndpointsConfig = field(default_factory=EndpointsConfig)
    device_types: DeviceTypeConfig = field(default_factory=DeviceTypeConfig)
    http_security: HttpSecurityConfig = field(default_factory=HttpSecurityConfig)
    gaming_services: GamingServicesConfig = field(default_factory=GamingServicesConfig)
    snmp_communities: Set[str] = field(default_factory=lambda: {"public", "private", "admin"})
    docker: DockerConfig = field(default_factory=DockerConfig)


# MAC Vendor Lookup Class
class MacVendorLookup:
    """
    Lookup MAC address vendors using OUI data.
    This class is currently not in use, but it might become useful again in the future.
    """
    DEFAULT_OUI_URL = "https://standards-oui.ieee.org/oui/oui.txt"
    DEFAULT_OUI_JSON_PATH = "oui.json"

    def __init__(self, logger: logging.Logger, oui_url: str = None, oui_json_path: str = None):
        """
        Initialize the MacVendorLookup with a logger, and optionally customize the OUI URL and JSON path.
        """
        self.logger = logger
        self.oui_url = oui_url if oui_url is not None else self.DEFAULT_OUI_URL
        self.oui_json_path = oui_json_path if oui_json_path is not None else self.DEFAULT_OUI_JSON_PATH
        self.oui_dict = self.load_oui_data()

    def load_oui_data(self) -> Dict[str, str]:
        """
        Load OUI data from a local JSON file or download and parse it from the IEEE website.
        """
        if os.path.exists(self.oui_json_path):
            self.logger.debug(f"Loading OUI data from local '{self.oui_json_path}' file.")
            try:
                with open(self.oui_json_path, "r") as f:
                    data = json.load(f)
                # Check if data has 'timestamp' and 'data'
                if isinstance(data, dict) and 'data' in data:
                    self.logger.debug("OUI data loaded successfully from local JSON file.")
                    return data['data']
                elif isinstance(data, dict):
                    self.logger.debug("OUI data format from local JSON file is unexpected. Proceeding to download.")
            except Exception as e:
                self.logger.error(f"Failed to load local OUI JSON data: {e}")

        # Download and parse OUI data
        self.logger.debug(f"Downloading OUI data from {self.oui_url}.")
        try:
            response = requests.get(self.oui_url, timeout=10)
            if response.status_code == 200:
                oui_text = response.text
                self.logger.debug("OUI data downloaded successfully.")
                data = self.parse_oui_txt(oui_text)
                with open(self.oui_json_path, "w") as f:
                    json.dump({"timestamp": time.time(), "data": data}, f, indent=2)
                self.logger.debug(f"OUI data parsed and saved to '{self.oui_json_path}'.")
                return data
            else:
                self.logger.error(f"Failed to download OUI data: HTTP {response.status_code}")
        except Exception as e:
            self.logger.error(f"Exception while downloading OUI data: {e}")
        return {}

    def parse_oui_txt(self, text: str) -> Dict[str, str]:
        """
        Parse the OUI text data and return a dictionary mapping MAC prefixes to vendor names.
        """
        oui_dict: Dict[str, str] = {}
        lines = text.splitlines()
        for line in lines:
            if "(hex)" in line:
                parts = line.split("(hex)")
                if len(parts) >= 2:
                    mac_prefix = parts[0].strip().replace("-", "").upper()
                    company = parts[1].strip()
                    if len(mac_prefix) == 6:
                        oui_dict[mac_prefix] = company
        return oui_dict

    def get_vendor(self, mac: str) -> str:
        """
        Get the vendor name for a given MAC address.
        """
        if not mac:
            self.logger.warning("Empty MAC address provided.")
            return "Unknown"

        # Normalize MAC address
        mac_clean = mac.upper().replace(":", "").replace("-", "").replace(".", "")
        if len(mac_clean) < 6:
            self.logger.warning(f"Invalid MAC address format: {mac}")
            return "Unknown"

        mac_prefix = mac_clean[:6]
        oui_entry = self.oui_dict.get(mac_prefix, "Unknown")
        self.logger.debug(f"MAC Prefix: {mac_prefix}, Vendor: {oui_entry}")
        return oui_entry


# Device Classifier Class
class DeviceClassifier:
    """
    Classify devices based on their attributes.
    """
    def __init__(self, logger: logging.Logger, config: AppConfig):
        """
        Initialize the DeviceClassifier with a logger and configuration.
        """
        self.logger = logger
        self.config = config

    def classify(self, devices: List[Device]) -> Dict[str, List[Device]]:
        """
        Classify the list of devices into categories.
        """
        classified = {
            "Router": [],
            "Switch": [],
            "Printer": [],
            "Phone": [],
            "Smart": [],
            "Game": [],
            "Computer": [],
            "Unknown": []
        }

        for device in devices:
            device_type = self.infer_device_type(device)
            classified[device_type].append(device)

        # Remove empty categories
        classified = {k: v for k, v in classified.items() if v}

        return classified

    def infer_device_type(self, device: Device) -> str:
        """
        Infer the device type based on its attributes.
        """
        matched_device_type = "Unknown"
        highest_priority = float('inf')
        mac_address = device.mac_address if device.mac_address else 'N/A'

        for device_type in sorted(self.config.device_types.device_types, key=lambda dt: dt.priority):
            if device_type.matches(device):
                if device_type.priority < highest_priority:
                    matched_device_type = device_type.name
                    highest_priority = device_type.priority
                    self.logger.debug(f"Device {mac_address} matched {matched_device_type} with priority {device_type.priority}.")

        if matched_device_type == "Unknown":
            self.logger.debug(f"Device {mac_address} classified as Unknown.")
        else:
            self.logger.debug(f"Device {mac_address} classified as {matched_device_type}.")

        return matched_device_type


# Base class for all commands
class BaseCommand(ABC):
    def __init__(self, args: argparse.Namespace, logger: logging.Logger, config: AppConfig):
        """
        Initialize the BaseCommand with arguments and logger.
        """
        self.args = args
        self.logger = logger
        self.config = config

    @abstractmethod
    def execute(self) -> None:
        """
        Execute the command.
        """
        pass

    def print_table(self, title: str, columns: List[str], rows: List[List[str]]) -> None:
        """
        Print a table with the given title, columns, and rows.
        """
        if RICH_AVAILABLE:
            table = Table(title=title, box=box.MINIMAL_DOUBLE_HEAD)
            for col in columns:
                table.add_column(col, style="cyan", overflow="fold", no_wrap=False)
            for row in rows:
                table.add_row(*row)
            console.print(table)
        else:
            print(f"\n{title}")
            print("-" * len(title))
            print("\t".join(columns))
            for row in rows:
                print("\t".join(row))
            print()


# Base class for all diagnostics
class BaseDiagnostics(ABC):
    """
    Abstract base class for device diagnostics.
    """
    def __init__(self, device_type: str, device: Device, logger: logging.Logger, args: argparse.Namespace, config: AppConfig):
        """
        Initialize with device information and a logger.
        """
        self.device_type = device_type
        self.device = device
        self.logger = logger
        self.args = args
        self.config = config
        self.tools = SharedDiagnosticsTools(device, logger)

    @abstractmethod
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        """
        Perform diagnostics on the device.
        """
        pass

    def create_issue(self, description: str, port: int) -> DiagnoseIssue:
        """
        Create a DiagnoseIssue instance with the device's details.
        """
        hostname = self.tools.get_device_hostname() or ''
        ip = self.tools.get_device_ip() or ''

        product = ''
        for available_port in self.device.ports:
            if available_port.port_id == port and available_port.state.lower() == "open":
                product = available_port.service.product
                break

        return DiagnoseIssue(
            device_type=self.device_type,
            hostname=hostname,
            ip=ip,
            port=port,
            product=product,
            description=description
        )


# General Device Diagnostics Class
class SharedDiagnosticsTools:
    def __init__(self, device: Device, logger: logging.Logger):
        """
        Initialize with device information and a logger.
        """
        self.device = device
        self.logger = logger

    def truncate_string(self, text: str, max_length: int, collapse: bool = False) -> str:
        """
        Truncate a string to the specified maximum length.
        Optionally collapse whitespace and newlines.
        """
        if collapse:
            text = re.sub(r"\W+", " ", text)

        if len(text) > max_length:
            truncated_text = text[:max_length] + "..."
            return truncated_text
        else:
            return text

    def make_http_request(
            self,
            url: str,
            hostname: Optional[str] = None,
            method: str = 'GET',
            params: Optional[Dict[str, Any]] = None,
            data: Optional[Dict[str, Any]] = None,
            json_payload: Optional[Any] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout: int = 5,
            verify: Optional[bool] = None,
            auth: Optional[Tuple[str, str]] = None
    ) -> Optional[requests.Response]:
        """
        Makes an HTTP/HTTPS request to the specified URL with optional parameters.
        """
        try:
            # Parse the URL to determine the protocol
            parsed_url = urlparse(url)
            protocol = parsed_url.scheme.lower()

            if protocol not in ['http', 'https']:
                self.logger.error(f"Unsupported protocol '{protocol}' in URL: {url}")
                return None

            # Determine SSL verification
            if verify is None:
                verify = protocol == 'https'

            # Prepare headers
            request_headers = headers.copy() if headers else {}
            if hostname:
                request_headers['Host'] = hostname

            # Log the request details
            self.logger.debug(f"Preparing to make a {'encrypted' if verify else 'plain'} {method.upper()} request to {url} (timeout: {timeout} seconds)")
            self.logger.debug(f"Headers: {request_headers}")
            if params:
                self.logger.debug(f"Query Parameters: {params}")
            if data:
                self.logger.debug(f"Form Data: {data}")
            if json_payload:
                self.logger.debug(f"JSON Payload: {json_payload}")

            # Make the HTTP request
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=request_headers,
                params=params,
                data=data,
                json=json_payload,
                timeout=timeout,
                verify=verify,
                auth=auth
            )

            # Log the response status
            self.logger.debug(f"Received response with status code: {response.status_code}")

            return response

        except requests.exceptions.RequestException as e:
            self.logger.info(f"HTTP request to {url} failed: {e}")
            raise e

    def has_open_port(self, port: int, protocol: str = 'tcp'):
        """
        Check if the device has an open port with the specified port number and protocol.
        """
        for port in self.device.ports:
            if port.port_id == port and port.protocol == protocol:
                return port.state.lower() == 'open'
        return False

    def get_device_ip(self) -> Optional[str]:
        """
        Get the first IP address of the device.
        """
        if self.device.ip_addresses:
            return self.device.ip_addresses[0]
        else:
            self.logger.error("No IP address found for the device.")
            return None

    def get_device_hostname(self) -> Optional[str]:
        """
        Get the first hostname of the device.
        """
        if self.device.hostnames:
            return self.device.hostnames[0]
        else:
            self.logger.debug(f"No hostname found for the device {self.get_device_ip()}.")
            return None

    def get_device_urls(self) -> List[str]:
        """
        Generates a list of URLs for all open ports that appear to be web servers.
        Uses http:// for plaintext web servers and https:// for TLS-enabled web servers.
        """
        urls: List[str] = []

        # Regular expression to detect HTTP responses in fingerprints
        http_pattern = re.compile(r"HTTP/\d\.\d", re.IGNORECASE)

        # Set of service names commonly associated with web servers
        web_service_names = {"http", "https"}

        # Iterate through all open ports
        for port in self.device.ports:
            if port.state.lower() != "open":
                continue  # Skip non-open ports

            service = port.service
            if not service:
                continue  # Skip ports without service information

            is_web = False
            uses_tls = False

            # Check if the service name indicates a web server
            if service.name and service.name.lower() in web_service_names:
                is_web = True

            # If not identified by name, check the service fingerprint for HTTP patterns
            if not is_web and service.service_fingerprint:
                if http_pattern.search(service.service_fingerprint):
                    is_web = True

            if not is_web:
                continue  # Not a web server

            # Determine if the service uses TLS
            # First, check if any script indicates SSL/TLS
            for script in service.scripts:
                if "ssl" in script.script_id.lower() or "tls" in script.script_id.lower():
                    uses_tls = True
                    break  # No need to check further scripts

            # If not determined by scripts, check the fingerprint for SSL
            if not uses_tls and service.service_fingerprint:
                if re.search(r"\bSSL\b", service.service_fingerprint, re.IGNORECASE):
                    uses_tls = True

            # Select the protocol based on TLS usage
            protocol = "https" if uses_tls else "http"

            # Select the IP address to use
            if not self.device.ip_addresses:
                continue  # No IP address available
            ip = self.device.ip_addresses[0]  # Use the first IP address

            # Construct the URL
            # Default ports for HTTP and HTTPS don't need to be included
            if (protocol == "http" and port.port_id == 80) or (protocol == "https" and port.port_id == 443):
                url = f"{protocol}://{ip}"
            else:
                url = f"{protocol}://{ip}:{port.port_id}"

            urls.append(url)

        return urls

    def determine_port_from_url(self, url: str) -> int:
        """
        Determine the port and protocol from a URL.
        """
        parsed_url = urlparse(url)
        port = parsed_url.port
        protocol = parsed_url.scheme.lower()
        if not port:
            port = 443 if protocol == 'https' else 80
        return port


# Common Diagnostics
class ExternalResourcesDiagnostics(BaseDiagnostics):
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        issues.extend(self.extract_nmap_scripts())

        urls: List[str] = self.tools.get_device_urls()
        for url in urls:
            if self.args.all or self.args.nikto:
                issues.extend(self.scan_with_nikto(url, self.args.execution))

            if self.args.all or self.args.golismero:
                issues.extend(self.scan_with_golismero(url, self.args.execution))

        return issues

    def extract_nmap_scripts(self) -> List[DiagnoseIssue]:
        """
        Extract and parse Nmap scripts from the device's services.
        """
        issues: List[DiagnoseIssue] = []

        for port in self.device.ports:
            if port.service:
                for script in port.service.scripts:
                    if script.script_id in ['http-title', 'fingerprint-strings']:
                        continue

                    truncated_output = self.tools.truncate_string(script.output, 250, collapse=True)
                    issue_description = f"Nmap {script.script_id}: {truncated_output}"
                    issues.append(self.create_issue(issue_description, port.port_id))
                    self.logger.info(f"Created nmap script issue {script.script_id} on port {port.port_id}: {truncated_output}")

        return issues

    def scan_with_nikto(self, target_url: str, execution: ExecutionMode) -> List[DiagnoseIssue]:
        """
        Perform a Nikto scan on the web service and create issues based on the findings.
        """
        issues: List[DiagnoseIssue] = []

        # Check if Nikto is installed or Docker image is available
        if execution == ExecutionMode.NATIVE:
            if not shutil.which('nikto'):
                self.logger.warning("Nikto is not installed. Skipping Nikto scan.")
                return issues
        elif execution == ExecutionMode.DOCKER:
            docker_image = self.config.docker.images.get('nikto')
            if not docker_image:
                self.logger.warning("Docker image for Nikto not set in configuration. Skipping Nikto scan.")
                return issues
        else:
            self.logger.warning(f"Unsupported execution mode '{execution}'. Skipping Nikto scan.")
            return issues

        self.logger.debug(f"Starting Nikto scan on {target_url} with execution mode '{execution}'.")

        # Create a temporary file to store the Nikto JSON output
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as temp_output_file:
            temp_output_path = temp_output_file.name

        try:
            # Construct the Nikto command based on execution mode
            if execution == ExecutionMode.NATIVE:
                nikto_command = [
                    'nikto',
                    '-h', target_url,
                    '-Format', 'json',
                    '-output', temp_output_path
                ]
            elif execution == ExecutionMode.DOCKER:
                nikto_command = [
                    'docker', 'run', '--rm',
                    '-v', f"{os.path.abspath(temp_output_path)}:/output.json",
                    docker_image,
                    '-h', target_url,
                    '-Format', 'json',
                    '-output', '/output.json'
                ]

            self.logger.debug(f"Executing command: {' '.join(nikto_command)}")

            # Execute the Nikto scan
            subprocess.run(
                nikto_command,
                check=True,
                capture_output=True,
                text=True
            )
            self.logger.debug("Nikto scan completed. Parsing results from output file.")

            # Read the scan results from the temporary JSON file
            with open(temp_output_path, 'r') as f:
                nikto_output = f.read()

            # Parse the Nikto JSON output
            try:
                data = json.loads(nikto_output)
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to decode Nikto JSON output for {target_url}: {e}")
                return issues

            # Check if 'vulnerabilities' key exists
            vulnerabilities = data.get('vulnerabilities', [])
            if not vulnerabilities:
                self.logger.info(f"No vulnerabilities found by Nikto on ({target_url}).")
                return issues

            # Iterate through each vulnerability found by Nikto
            for vuln in vulnerabilities:
                description = vuln.get('msg', 'No description provided.').strip()
                uri = vuln.get('url', 'N/A').strip()
                method = vuln.get('method', 'UNKNOWN').strip()

                issue_description = f"Nikto: {description} [URI: {uri}, Method: {method}]"

                # Create an issue for each Nikto finding
                port = self.tools.determine_port_from_url(uri)
                issues.append(self.create_issue(issue_description, port))
                self.logger.info(f"Nikto issue on ({target_url}): {issue_description}")

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Nikto scan failed on {target_url}: {e.stderr.strip()}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Nikto JSON output for {target_url}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error during Nikto scan on {target_url}: {e}")
        finally:
            try:
                os.remove(temp_output_path)
                self.logger.debug(f"Removed temporary output file {temp_output_path}.")
            except Exception as e:
                self.logger.warning(f"Failed to remove temporary output file {temp_output_path}: {e}")

        return issues

    def scan_with_golismero(self, target_url: str, execution: ExecutionMode) -> List[DiagnoseIssue]:
        """
        Perform a Golismero scan on the target device and parse the results.
        """
        issues: List[DiagnoseIssue] = []

        # Check if Golismero is installed or Docker image is available
        if execution == ExecutionMode.NATIVE:
            if not shutil.which('golismero.py'):
                self.logger.warning("Golismero is not installed. Skipping Golismero scan.")
                return issues
        elif execution == ExecutionMode.DOCKER:
            docker_image = self.config.docker.images.get('golismero')
            if not docker_image:
                self.logger.warning("Docker image for Golismero not set in configuration. Skipping Golismero scan.")
                return issues
        else:
            self.logger.warning(f"Unsupported execution mode '{execution}'. Skipping Golismero scan.")
            return issues

        self.logger.debug(f"Starting Golismero scan on {target_url} with execution mode '{execution}'.")

        # Create a temporary file to store the scan output
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as temp_output_file:
            temp_output_path = temp_output_file.name

        try:
            # Construct the Golismero scan command based on execution mode
            if execution == ExecutionMode.NATIVE:
                golismero_command = [
                    'golismero.py',
                    'scan',
                    target_url,
                    '-o', temp_output_path
                ]
            elif execution == ExecutionMode.DOCKER:
                golismero_command = [
                    'docker', 'run', '--rm',
                    '-v', f"{os.path.abspath(temp_output_path)}:/output.json",
                    docker_image,
                    'scan',
                    target_url,
                    '-o', '/output.json'
                ]

            self.logger.debug(f"Executing command: {' '.join(golismero_command)}")

            # Execute the Golismero scan
            subprocess.run(
                golismero_command,
                check=True,
                capture_output=True,
                text=True
            )
            self.logger.debug("Golismero scan completed. Parsing results from output file.")

            # Read the scan results from the output file
            with open(temp_output_path, 'r') as f:
                scan_results = json.load(f)

            # Log general information from the scan summary
            summary = scan_results.get('summary', {})
            self.logger.info(f"Golismero Scan Summary for {target_url}:")
            self.logger.info(f"Report Time: {summary.get('report_time')}")
            self.logger.info(f"Run Time: {summary.get('run_time')}")
            self.logger.info(f"Audit Name: {summary.get('audit_name')}")
            self.logger.info(f"Number of Vulnerabilities: {len(scan_results.get('vulnerabilities', {}))}")

            # Process each vulnerability
            vulnerabilities = scan_results.get('vulnerabilities', {})
            for vuln_id, vulnerability in vulnerabilities.items():
                level = vulnerability.get('level', 'informational').lower()
                title = vulnerability.get('title', 'No title')
                description = vulnerability.get('description', 'No description provided.')
                solution = vulnerability.get('solution', 'No solution provided.')

                # Only create issues for vulnerabilities that are not informational
                if level != 'informational':
                    issue_description = f"{title}: {description} | Solution: {solution}"
                    port = self.tools.determine_port_from_url(target_url)
                    issues.append(self.create_issue(f"Golismero [{level.upper()}]: {issue_description}", port))
                    self.logger.info(f"Golismero issue on {target_url}: {level.capitalize()} - {title} - {description}")
                else:
                    # Log informational findings without creating issues
                    self.logger.info(f"Golismero info on {target_url}: {title} - {description}")

            # Optionally, log additional resources information if needed
            resources = scan_results.get('resources', {})
            for resource_id, resource in resources.items():
                self.logger.info(f"Resource: {resource.get('display_name')} - {resource.get('display_content')}")

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Golismero scan failed on {target_url}: {e.stderr.strip()}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Golismero JSON output for {target_url}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error during Golismero scan on {target_url}: {e}")
        finally:
            try:
                os.remove(temp_output_path)
                self.logger.debug(f"Removed temporary output file {temp_output_path}.")
            except Exception as e:
                self.logger.warning(f"Failed to remove temporary output file {temp_output_path}: {e}")

        return issues


class HttpSecurityDiagnostics(BaseDiagnostics):
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        urls: List[str] = self.tools.get_device_urls()
        hostname: str = self.tools.get_device_hostname()
        vendor: str = self.device.vendor or ''

        for url in urls:
            issues.extend(self.validate_web_service_response(url, hostname))
            issues.extend(self.check_http_admin_interface(url, hostname, vendor))

        return issues

    def validate_web_service_response(self, url: str, hostname: str) -> List[DiagnoseIssue]:
        """
        Perform comprehensive checks on the specified protocol's service, including response codes and security headers.
        """
        issues: List[DiagnoseIssue] = []

        port = self.tools.determine_port_from_url(url)
        try:
            response = self.tools.make_http_request(url, hostname)
            if response is None or not response.ok:
                issues.append(self.create_issue(f"Request to {url} failed, response code {response.status_code if response else 'none'}", port))
                self.logger.info(f"Response code {response.status_code if response else 'none'} on {url} for {hostname}")

            issues.extend(self._check_security_headers(response))
        except requests.exceptions.SSLError as ssl_err:
            issues.append(self.create_issue(f"SSL Error on {url} - {ssl_err}", port))
            self.logger.info(f"SSL Error for on {url} for {hostname}: {ssl_err}")
        except requests.exceptions.ConnectionError as conn_err:
            issues.append(self.create_issue(f"Connection Error on {url} - {conn_err}", port))
            self.logger.info(f"Connection error on {url} for {hostname}: {conn_err}")
        except requests.exceptions.Timeout:
            issues.append(self.create_issue(f"Timeout while connecting to {url}", port))
            self.logger.info(f"Timeout while connecting to {url} for {hostname}")
        except Exception as e:
            self.logger.info(f"Unexpected error on {url} for {hostname}: {e}")

        return issues

    def _check_security_headers(self, response: requests.Response) -> List[DiagnoseIssue]:
        """
        Check for the presence of critical security headers in the HTTP response.
        """
        issues: List[DiagnoseIssue] = []

        if response is None:
            return issues

        security_headers = self.config.http_security.security_headers

        missing_headers = [header for header in security_headers if header.lower() not in response.headers.lower_items()]
        if missing_headers:
            port = self.tools.determine_port_from_url(response.url)
            issues.append(self.create_issue(f"Missing security headers: {', '.join(missing_headers)}", port))
            self.logger.info(f"Missing security headers: {', '.join(missing_headers)}")
        return issues

    def check_http_admin_interface(self, url: str, hostname: str, vendor: str) -> List[DiagnoseIssue]:
        """
        Generic method to check admin interfaces over the specified protocol.
        """
        issues = []
        try:
            self.logger.debug(f"Checking admin interfaces on {url} for vendor '{vendor}'.")
            admin_endpoints = self.config.endpoints.get_vendor_config(vendor)['sensitive_endpoints']
            for endpoint in admin_endpoints:
                try:
                    response = self.tools.make_http_request(url, hostname, verify=False)
                    if response is None:
                        continue
                    if 200 <= response.status_code < 300:
                        # Admin interface is accessible
                        port = self.tools.determine_port_from_url(url)
                        issues.append(self.create_issue(f"Admin interface {url}{endpoint} is accessible", port))
                        self.logger.info(f"Admin interface {url}{endpoint} is accessible.")
                        break  # Assume one admin interface is sufficient
                except requests.RequestException:
                    continue  # Try the next endpoint
        except Exception as e:
            self.logger.info(f"Error while checking admin interface on {url}: {e}")
        return issues


class HttpAuthenticationDiagnostics(BaseDiagnostics):
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []

        if self.args.all or self.args.credentials:
            urls: List[str] = self.tools.get_device_urls()
            hostname = self.tools.get_device_hostname()
            for url in urls:
                issues.extend(self.check_default_credentials(url, hostname))

        return issues

    def check_default_credentials(self, url: str, hostname: Optional[str]) -> List[DiagnoseIssue]:
        """
        Check for default credentials on the device based on the vendor.
        """
        issues: List[DiagnoseIssue] = []

        if not BEAUTIFULSOUP_AVAILABLE:
            self.logger.error("BeautifulSoup is not installed. Install it using 'pip install beautifulsoup4'.")
            return issues

        try:
            self.logger.debug(f"Initiating default credentials check on {url}.")

            # Retrieve the list of default credentials for the specified vendor
            vendor: str = self.device.vendor or ''
            credentials = self.config.credentials.get_vendor_credentials(vendor)
            self.logger.debug(f"Retrieved {len(credentials)} default credentials for vendor '{vendor}' to check on {url}.")

            # Determine the authentication method required by the device's admin interface
            auth_method = self._identify_authentication_method(url, hostname)
            if not auth_method:
                self.logger.info(f"No authentication required for {url}. Skipping default credentials check.")
                return issues  # No authentication needed; no default credentials issue

            self.logger.debug(f"Authentication method for {url}: {auth_method}")

            # Iterate through each set of default credentials and attempt authentication
            for cred in credentials:
                username = cred.get('username')
                password = cred.get('password')
                if not username or not password:
                    self.logger.warning(f"Invalid credential entry: {cred}. Skipping.")
                    continue  # Skip invalid credential entries

                self.logger.debug(f"Attempting to authenticate on {url} with username='{username}' and password='{password}'.")

                if self._attempt_authentication(url, hostname, username, password, auth_method):
                    issue_description = f"Default credentials used: {username}/{password}"
                    port = self.tools.determine_port_from_url(url)
                    issues.append(self.create_issue(issue_description, port))
                    self.logger.info(f"Default credentials successfully used on {url}: {username}/{password}")
                    break  # Stop after first successful authentication
        except Exception as e:
            self.logger.info(f"Unexpected error while checking default credentials on {url}: {e}")
        return issues

    def _identify_authentication_method(self, url: str, hostname: Optional[str]) -> Optional[str]:
        """
        Identify the authentication method required by the device's admin interface.
        """
        try:
            self.logger.debug(f"Sending unauthenticated request to {url} to determine authentication method.")

            response = self.tools.make_http_request(url, hostname, verify=False)
            if response is None:
                self.logger.debug(f"No response received from {url}. Assuming no authentication required.")
                return None

            if response.status_code == 401:
                self.logger.debug(f"Received 401 Unauthorized from {url}. Assuming HTTP Basic Authentication.")
                return 'basic'
            elif response.status_code == 200:
                # Analyze the response content to detect a login form
                soup = BeautifulSoup(response.text, 'html.parser')
                form = soup.find('form')
                if form:
                    password_inputs = form.find_all('input', {'type': 'password'})
                    if password_inputs:
                        self.logger.debug(f"Login form detected on {url}. Assuming Form-Based Authentication.")
                        return 'form'
                self.logger.debug(f"No authentication required as no login form detected on {url}.")
                return None
            else:
                self.logger.debug(f"Received unexpected status code {response.status_code} from {url}. Assuming no authentication.")
                return None
        except Exception as e:
            self.logger.info(f"Unexpected error while determining authentication method for {url}: {e}")
        return None

    def _attempt_authentication(self, url: str, hostname: Optional[str], username: str, password: str, auth_method: str) -> bool:
        """
        Attempt to authenticate to the device's admin interface using the specified authentication method.
        """
        try:
            if auth_method == 'basic':
                return self._attempt_basic_authentication(url, hostname, username, password)
            elif auth_method == 'form':
                return self._attempt_form_based_authentication(url, hostname, username, password)
            else:
                self.logger.error(f"Unsupported authentication method '{auth_method}' for {url}.")
        except Exception as e:
            self.logger.info(f"Unexpected error during authentication to {url} with username='{username}': {e}")
        return False

    def _attempt_basic_authentication(self, url: str, hostname: Optional[str], username: str, password: str) -> bool:
        """
        Attempt HTTP Basic Authentication.
        """
        headers = {'Host': hostname if hostname else "N/A"}
        self.logger.debug(f"Initiating HTTP Basic Authentication to {url} with username='{username}'.")

        try:
            response = self.tools.make_http_request(
                url=url,
                hostname=hostname,
                auth=(username, password),
                headers=headers,
                verify=False
            )

            if response is None:
                self.logger.debug(f"No response received during HTTP Basic Authentication for {username}/{password} on {url}.")
                return False

            if response.status_code in [200, 302]:
                self.logger.debug(f"HTTP Basic Authentication succeeded for {username}/{password} on {url} with status code {response.status_code}.")
                return True
            else:
                self.logger.debug(f"HTTP Basic Authentication failed for {username}/{password} on {url} with status code {response.status_code}.")
        except Exception as e:
            self.logger.debug(f"HTTP Basic Authentication request to {url} with {username}/{password} failed: {e}")
        return False

    def _attempt_form_based_authentication(self, url: str, hostname: Optional[str], username: str, password: str) -> bool:
        """
        Attempt Form-Based Authentication by submitting credentials through the login form.
        """
        headers = {'Host': hostname if hostname else "N/A"}
        self.logger.debug(f"Fetching login form from {url} for form-based authentication.")

        try:
            # Fetch the login page to retrieve the form details
            response = self.tools.make_http_request(
                url=url,
                hostname=hostname,
                headers=headers,
                verify=False
            )

            if response is None or response.status_code != 200:
                self.logger.debug(f"Failed to retrieve login page from {url}. Status code: {response.status_code if response else 'No Response'}")
                return False

            soup = BeautifulSoup(response.text, 'html.parser')
            form = self._extract_login_form(soup)
            if not form:
                self.logger.debug(f"No suitable login form found on {url}.")
                return False

            form_details = self._parse_login_form(form, url)
            if not form_details:
                self.logger.debug(f"Failed to parse login form on {url}.")
                return False

            form_action, form_method, form_data = form_details

            # Populate form data with credentials
            form_data = self._populate_form_data(form_data, username, password)

            self.logger.debug(f"Submitting form to {form_action} with data: {form_data}")

            # Submit the form with the populated data
            if form_method.lower() == 'post':
                post_response = self.tools.make_http_request(
                    url=form_action,
                    hostname=hostname,
                    method='POST',
                    data=form_data,
                    headers=headers,
                    verify=False
                )
            else:
                # For GET method forms
                post_response = self.tools.make_http_request(
                    url=form_action,
                    hostname=hostname,
                    method='GET',
                    params=form_data,
                    headers=headers,
                    verify=False
                )

            # Determine if authentication was successful based on response
            if post_response and post_response.status_code in [200, 302]:
                self.logger.debug(f"Form-Based Authentication succeeded for {username}/{password} on {form_action} with status code {post_response.status_code}.")
                return True
            else:
                self.logger.debug(f"Form-Based Authentication failed for {username}/{password} on {form_action} with status code {post_response.status_code if post_response else 'No Response'}.")
        except Exception as e:
            self.logger.debug(f"Form-Based Authentication request to {url} with {username}/{password} failed: {e}")
        return False

    def _extract_login_form(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """
        Extract the login form from the parsed HTML soup.
        """
        # Attempt to find form elements that likely represent a login form
        forms = soup.find_all('form')
        for form in forms:
            # Check for input fields that indicate a login form
            input_types = [input_tag.get('type', '').lower() for input_tag in form.find_all('input')]
            if 'password' in input_types:
                return form
        return None

    def _parse_login_form(self, form: BeautifulSoup, base_url: str) -> Optional[Tuple[str, str, Dict[str, str]]]:
        """
        Parse the login form to extract action URL, method, and input fields.
        """
        try:
            # Extract form action (target URL)
            action = form.get('action')
            if not action:
                action_url = base_url  # Default to current URL if action is not specified
            elif not action.startswith('http'):
                # Handle relative URLs
                if action.startswith('/'):
                    parsed_url = urlparse(base_url)
                    action_url = f"{parsed_url.scheme}://{parsed_url.netloc}{action}"
                else:
                    # Relative path without leading slash
                    action_url = f"{base_url}/{action}"
            else:
                action_url = action

            # Extract form method (GET or POST)
            method = form.get('method', 'post').lower()

            # Extract all input fields within the form
            inputs = form.find_all('input')
            form_data = {}
            for input_tag in inputs:
                input_name = input_tag.get('name')
                input_type = input_tag.get('type', '').lower()
                input_value = input_tag.get('value', '')

                if not input_name:
                    continue  # Skip inputs without a name attribute

                if input_type == 'password':
                    form_data[input_name] = ''  # Placeholder for password
                elif input_type in ['text', 'email', 'username']:
                    form_data[input_name] = ''  # Placeholder for username
                elif input_type in ['hidden', 'submit']:
                    form_data[input_name] = input_value
                else:
                    form_data[input_name] = input_value  # Default handling

            return action_url, method, form_data
        except Exception as e:
            self.logger.info(f"Error parsing login form: {e}")
        return None

    def _populate_form_data(self, form_data: Dict[str, str], username: str, password: str) -> Dict[str, str]:
        """
        Populate the form data with the provided username and password.
        """
        for key, value in form_data.items():
            if 'user' in key.lower():
                form_data[key] = username
            elif 'pass' in key.lower():
                form_data[key] = password
        return form_data


class SnmpSecurityDiagnostics(BaseDiagnostics):
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        ip: str = self.tools.get_device_ip()

        issues.extend(self.check_snmp_configuration(ip))
        return issues

    def check_snmp_configuration(self, ip: str) -> List[DiagnoseIssue]:
        """
        Check SNMP configuration for potential vulnerabilities.
        """
        issues: List[DiagnoseIssue] = []

        snmp_port = 161
        if not self.tools.has_open_port(snmp_port, 'udp'):
            return issues  # Skip SNMP check if port is not open

        try:
            self.logger.debug(f"Checking SNMP configuration on {ip}.")
            # Example logic: Attempt SNMP queries with default community strings
            for community in self.config.snmp_communities:

                if self._snmp_query(ip, snmp_port, community):
                    issues.append(self.create_issue(f"SNMP is accessible with community string '{community}'.", snmp_port))
                    self.logger.info(f"SNMP is accessible with community string '{community}' on {ip}.")
                    break  # Assume one accessible SNMP community is sufficient
        except Exception as e:
            self.logger.info(f"Error while checking SNMP configuration on {ip}: {e}")
        return issues

    def _snmp_query(self, ip: str, port: int, community: str) -> bool:
        """
        Perform an SNMP GET request to the specified IP using the provided community string.
        Returns True if the community string is valid (i.e., SNMP is accessible), False otherwise.
        """
        timeout = 2  # Seconds

        try:
            # Create a UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)

            # SNMP GET Request Packet Construction (SNMPv1)
            # ASN.1 BER encoding

            # Version: SNMPv1 (0)
            version = b'\x02\x01\x00'

            # Community
            community_bytes = community.encode('utf-8')
            community_packed = b'\x04' + struct.pack('B', len(community_bytes)) + community_bytes

            # PDU (GetRequest-PDU)
            pdu_type = 0xA0  # GetRequest-PDU

            # Request ID: arbitrary unique identifier
            request_id = 1
            request_id_packed = b'\x02\x01' + struct.pack('B', request_id)

            # Error Status and Error Index
            error_status = b'\x02\x01\x00'  # noError
            error_index = b'\x02\x01\x00'   # 0

            # Variable Binding: sysDescr.0 OID
            oid = b'\x06\x08\x2B\x06\x01\x02\x01\x01\x01\x00'  # OID for sysDescr.0
            value = b'\x05\x00'  # NULL
            varbind = b'\x30' + struct.pack('B', len(oid) + len(value)) + oid + value

            # Variable Binding List
            varbind_list = b'\x30' + struct.pack('B', len(varbind)) + varbind

            # PDU Body
            pdu_body = request_id_packed + error_status + error_index + varbind_list
            pdu = struct.pack('B', pdu_type) + struct.pack('B', len(pdu_body)) + pdu_body

            # Full SNMP Packet
            snmp_packet = b'\x30' + struct.pack('B', len(version) + len(community_packed) + len(pdu)) + version + community_packed + pdu

            # Send SNMP GET request
            sock.sendto(snmp_packet, (ip, port))
            self.logger.debug(f"Sent SNMP GET request to {ip} with community '{community}'.")

            # Receive response
            try:
                data, _ = sock.recvfrom(4096)
                self.logger.debug(f"Received SNMP response from {ip}.")

                # Basic validation of SNMP response
                if data:
                    # Check if the response is a GetResponse-PDU (0xA2)
                    pdu_response_type = data[0]
                    if pdu_response_type == 0xA2:
                        self.logger.info(f"SNMP community '{community}' is valid on {ip}.")
                        return True
            except socket.timeout:
                self.logger.debug(f"SNMP GET request to {ip} with community '{community}' timed out.")
            finally:
                sock.close()

        except Exception as e:
            self.logger.info(f"Error while performing SNMP GET to {ip} with community '{community}': {e}")

        self.logger.info(f"SNMP community '{community}' is invalid or not accessible on {ip}.")
        return False


# Device-Type Specific Diagnostics Classes
class RouterDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics specific to routers.
    """
    DEVICE_TYPE = "Router"

    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class PrinterDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics specific to printers.
    """
    DEVICE_TYPE = "Printer"

    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class PhoneDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics specific to VoIP and mobile phones.
    """
    DEVICE_TYPE = "Phone"

    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class SmartDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics specific to smart devices, including IoT devices.
    """
    DEVICE_TYPE = "SmartDevice"

    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class GameDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics specific to game consoles like PlayStation, Xbox, and Nintendo Switch.
    """
    DEVICE_TYPE = "GameConsole"

    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class ComputerDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics for laptops, desktops, and phones.
    """
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


class OtherDeviceDiagnostics(BaseDiagnostics):
    """
    Perform diagnostics for other types of devices.
    """
    def diagnose(self) -> Optional[List[DiagnoseIssue]]:
        issues: List[DiagnoseIssue] = []
        return issues


# Network Scanner and Classifier
class NetworkScanner:
    """
    Scan the network and classify connected devices.
    """
    def __init__(self, args: argparse.Namespace, logger: logging.Logger, config: AppConfig):
        """
        Initialize the network scanner with arguments and logger.
        """
        self.args = args
        self.logger = logger
        self.config = config
        self.ipv6_enabled = args.ipv6

    def execute(self) -> Dict[str, List[Device]]:
        """
        Execute the network scanning and classification.
        """
        self.logger.info("Scanning the network for connected devices...")
        devices = self.scan_network()
        if not devices:
            self.logger.error("No devices found on the network.")
            sys.exit(1)

        return self.classify_devices(devices)

    def scan_network(self) -> List[Device]:
        """
        Scan the active subnets using nmap to discover devices.
        """
        try:
            # Dynamically determine the active subnets
            subnets = self.get_active_subnets()
            if not subnets:
                self.logger.error("No devices found on the network.")
                return []

            all_devices: List[Device] = []
            for subnet in subnets:
                self.logger.debug(f"Scanning subnet: {subnet}")
                # Determine if subnet is IPv6 based on presence of ':'
                if '/' in subnet and ':' in subnet:
                    # IPv6 subnet
                    scan_command = ['sudo', 'nmap', '-A', '-T4', '-6', '-oX', '-', subnet]
                else:
                    # IPv4 subnet
                    scan_command = ['sudo', 'nmap', '-A', '-T4', '-oX', '-', subnet]

                self.logger.debug(f"Executing command: {' '.join(scan_command)}")
                result = subprocess.run(scan_command, capture_output=True, text=True)

                if result.returncode != 0:
                    self.logger.error(f"nmap scan failed for subnet {subnet}: {result.stderr.strip()}")
                    continue

                if not result.stdout.strip():
                    self.logger.error(f"nmap scan for subnet {subnet} returned empty output.")
                    if result.stderr:
                        self.logger.error(f"nmap stderr: {result.stderr.strip()}")
                    continue

                devices = self.parse_nmap_output(result.stdout)
                self.logger.debug(f"Found {len(devices)} devices in subnet {subnet}.")
                all_devices.extend(devices)
            return all_devices
        except FileNotFoundError:
            self.logger.error("nmap is not installed. Install it using your package manager.")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error during network scan: {e}")
            return []

    def get_active_subnets(self) -> List[str]:
        """
        Determine the active subnets based on the system's non-loopback IPv4 and IPv6 addresses.
        Excludes virtual interfaces by default unless self.args.virtual is True.
        """
        subnets = []
        try:
            # Retrieve IPv4 subnets
            result_v4 = subprocess.run(['ip', '-4', 'addr'], capture_output=True, text=True, check=True)
            lines_v4 = result_v4.stdout.splitlines()
            current_iface = None
            for line in lines_v4:
                if line.startswith(' '):
                    if 'inet ' in line:
                        parts = line.strip().split()
                        ip_cidr = parts[1]  # e.g., '192.168.1.10/24'
                        ip, prefix = ip_cidr.split('/')
                        prefix = int(prefix)
                        subnet = self.calculate_subnet(ip, prefix)
                        # Exclude loopback subnet
                        if not subnet.startswith("127."):
                            # Determine the interface name from previous non-indented line
                            if current_iface and (not self.is_virtual_interface(current_iface) or self.args.virtual):
                                subnets.append(subnet)
                else:
                    # New interface
                    iface_info = line.split(':', 2)
                    if len(iface_info) >= 2:
                        current_iface = iface_info[1].strip().split('@')[0]

            # If IPv6 is enabled, retrieve IPv6 subnets
            if self.ipv6_enabled:
                result_v6 = subprocess.run(['ip', '-6', 'addr'], capture_output=True, text=True, check=True)
                lines_v6 = result_v6.stdout.splitlines()
                current_iface = None
                for line in lines_v6:
                    if line.startswith(' '):
                        if 'inet6 ' in line:
                            parts = line.strip().split()
                            ip_cidr = parts[1]  # e.g., '2001:db8::1/64'
                            ip, prefix = ip_cidr.split('/')
                            prefix = int(prefix)
                            subnet = self.calculate_subnet(ip, prefix)
                            # Exclude loopback subnet
                            if not subnet.startswith("::1"):
                                # Determine the interface name from previous non-indented line
                                if current_iface and (not self.is_virtual_interface(current_iface) or self.args.virtual):
                                    subnets.append(subnet)
                    else:
                        # New interface
                        iface_info = line.split(':', 2)
                        if len(iface_info) >= 2:
                            current_iface = iface_info[1].strip().split('@')[0]

            # Remove duplicates
            subnets = list(set(subnets))
            self.logger.debug(f"Active subnets: {subnets}")
            return subnets
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get IP addresses: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error determining active subnets: {e}")
            return []

    def is_virtual_interface(self, iface: str) -> bool:
        """
        Determine if the given interface is virtual based on its name.
        """
        virtual_prefixes = ['docker', 'br-', 'veth', 'virbr', 'vmnet', 'lo']
        for prefix in virtual_prefixes:
            if iface.startswith(prefix):
                self.logger.debug(f"Interface '{iface}' identified as virtual.")
                return True
        return False

    def calculate_subnet(self, ip: str, prefix: int) -> str:
        """
        Calculate the subnet in CIDR notation based on IP and prefix.
        """
        ip_parts = ip.split('.')
        if prefix == 24:
            subnet = f"{'.'.join(ip_parts[:3])}.0/24"
        elif prefix == 16:
            subnet = f"{'.'.join(ip_parts[:2])}.0.0/16"
        elif prefix == 8:
            subnet = f"{ip_parts[0]}.0.0.0/8"
        else:
            # For other prefixes, use the exact CIDR
            subnet = f"{ip}/{prefix}"
        self.logger.debug(f"Calculated subnet for IP {ip}/{prefix}: {subnet}")
        return subnet

    def parse_nmap_output(self, output: str) -> List[Device]:
        """
        Parse the XML output from nmap to extract device information.
        """
        devices = []
        try:
            root = ET.fromstring(output)
            for host in root.findall('host'):
                status = host.find('status')
                if status is not None and status.get('state') != 'up':
                    continue

                device = Device()

                # Addresses
                addresses = host.findall('address')
                for addr in addresses:
                    addr_type = addr.get('addrtype')
                    address = addr.get('addr', 'N/A')
                    if addr_type in ['ipv4', 'ipv6']:
                        device.ip_addresses.append(address)
                    elif addr_type == 'mac':
                        device.mac_address = address
                        device.vendor = addr.get('vendor', 'Unknown')

                # Hostnames
                hostnames = host.find('hostnames')
                if hostnames is not None:
                    for name in hostnames.findall('hostname'):
                        hostname = name.get('name')
                        if hostname:
                            device.hostnames.append(hostname)

                # OS
                os_elem = host.find('os')
                if os_elem is not None:
                    for osmatch in os_elem.findall('osmatch'):
                        os_match = DeviceOsMatch(
                            accuracy=int(osmatch.get('accuracy', '0')),
                            name=osmatch.get('name', 'Unknown'),
                            os_family=None,
                            os_gen=None,
                            os_type=None,
                            vendor=None
                        )
                        # OS Classes and CPEs
                        for osclass in osmatch.findall('osclass'):
                            os_match.os_family = osclass.get('osfamily', os_match.os_family)
                            os_match.os_gen = osclass.get('osgen', os_match.os_gen)
                            os_match.os_type = osclass.get('type', os_match.os_type)
                            os_match.vendor = osclass.get('vendor', os_match.vendor)
                            for cpe in osclass.findall('cpe'):
                                if cpe.text:
                                    os_match.cpe_list.append(cpe.text)
                        device.os_matches.append(os_match)
                    if device.os_matches:
                        device.operating_system = device.os_matches[0].name
                    else:
                        device.operating_system = "Unknown"

                # Ports
                ports_elem = host.find('ports')
                if ports_elem is not None:
                    for port in ports_elem.findall('port'):
                        port_state = port.find('state')
                        if port_state is not None and port_state.get('state') == 'open':
                            service_elem = port.find('service')
                            service = None
                            if service_elem is not None:
                                service = DeviceService(
                                    confidence=service_elem.get('conf'),
                                    method=service_elem.get('method'),
                                    name=service_elem.get('name'),
                                    product=service_elem.get('product'),
                                    version=service_elem.get('version'),
                                    service_fingerprint=service_elem.get('servicefp'),
                                    cpe_list=[cpe.text for cpe in service_elem.findall('cpe') if cpe.text]
                                )
                                # Scripts
                                for script_elem in port.findall('script'):
                                    script = DeviceServiceScript(
                                        script_id=script_elem.get('id', ''),
                                        output=script_elem.get('output', '')
                                    )
                                    service.scripts.append(script)
                            port_info = DevicePort(
                                port_id=int(port.get('portid')),
                                protocol=port.get('protocol', 'unknown'),
                                state=port_state.get('state', 'unknown'),
                                reason=port_state.get('reason'),
                                service=service
                            )
                            device.ports.append(port_info)

                # OS Detection Ports Used
                os_elem = host.find('os')
                if os_elem is not None:
                    for portused in os_elem.findall('portused'):
                        proto = portused.get('proto', '')
                        portid = portused.get('portid', '')
                        state = portused.get('state', '')
                        port_info = f"{portid}/{proto} {state}"
                        if device.os_matches:
                            device.os_matches[0].ports_used.append(port_info)

                # Uptime
                uptime_elem = host.find('uptime')
                if uptime_elem is not None:
                    device.uptime = DeviceUptime(
                        last_boot_time=uptime_elem.get('lastboot', ''),
                        uptime_seconds=int(uptime_elem.get('seconds', '0'))
                    )

                # Distance
                distance_elem = host.find('distance')
                if distance_elem is not None:
                    device.distance = int(distance_elem.get('value', '0'))

                # Trace
                trace_elem = host.find('trace')
                if trace_elem is not None:
                    trace = DeviceTrace()
                    for hop in trace_elem.findall('hop'):
                        device_trace_hop = DeviceTraceHop(
                            host=hop.get('host'),
                            ip_address=hop.get('ipaddr'),
                            round_trip_time=float(hop.get('rtt')) if hop.get('rtt') else None,
                            time_to_live=int(hop.get('ttl')) if hop.get('ttl') else None
                        )
                        trace.hops.append(device_trace_hop)
                    device.trace = trace

                # Timing Information
                times_elem = host.find('times')
                if times_elem is not None:
                    device.rtt_variance = int(times_elem.get('rttvar', '0'))
                    device.smoothed_rtt = int(times_elem.get('srtt', '0'))
                    device.timeout = int(times_elem.get('to', '0'))

                devices.append(device)

        except ET.ParseError as e:
            self.logger.error(f"Failed to parse nmap XML output: {e}")
            self.logger.debug(f"nmap output was: {output}")
        except Exception as e:
            self.logger.error(f"Unexpected error during nmap parsing: {e}")
            self.logger.debug(f"nmap output was: {output}")
        return devices

    def classify_devices(self, devices: List[Device]) -> Dict[str, List[Device]]:
        """
        Classify devices into different categories.
        """
        classifier = DeviceClassifier(self.logger, self.config)
        classified = classifier.classify(devices)
        return classified


# Diagnostics Command
# Specific Diagnostics Classes
class DiagnosticsCommand(BaseCommand):
    """
    Perform automated network diagnostics.
    """
    DataclassType = TypeVar('DataclassType')

    def execute(self) -> None:
        """
        Execute the network diagnostics.
        """
        self.logger.info("Starting automated network diagnostics...")

        # Load devices from file or scan the network
        if self.args.input_file:
            classified_devices = self.load_devices_from_file(self.args.input_file)
        else:
            scanner = NetworkScanner(self.args, self.logger, self.config)
            classified_devices = scanner.execute()

        # Save devices to a JSON file if output is requested
        if self.args.output_file:
            self.save_devices_to_file(classified_devices, self.args.output_file)

        # Display discovered devices
        self.display_devices(classified_devices)

        # Perform diagnostics based on device type unless discovery is enabled
        if not self.args.discovery:
            self.perform_diagnostics(classified_devices)

    def perform_diagnostics(self, classified_devices: Dict[str, List[Device]]):
        """
        Perform diagnostics on the classified devices and collect issues.
        """
        issues_found: List[DiagnoseIssue] = []

        for device_type, devices in classified_devices.items():
            for device in devices:
                self.logger.info(f"Performing diagnostics on {device.ip_addresses[0]} ({device_type}).")
                diagnostics = self.get_diagnostic_classes(device_type, device)
                for diagnostic in diagnostics:
                    issues = diagnostic.diagnose()
                    for issue in issues:
                        if issue not in issues_found:
                            issues_found.append(issue)

        # Prepare rows by extracting values from each issue
        rows = [
            [
                issue.device_type,
                issue.hostname,
                issue.ip,
                str(issue.port),
                issue.product,
                issue.description
            ]
            for issue in issues_found
        ]

        # Display issues found
        if rows:
            columns = ["Device Type", "Hostname", "IP Address", "Port", "Product", "Issue"]
            self.print_table("Diagnostics Issues", columns, rows)
        else:
            self.logger.info("No issues detected during diagnostics.")

    def get_diagnostic_classes(self, device_type: str, device: Device) -> List[BaseDiagnostics]:
        """
        Get a list of diagnostic classes based on device type.
        """
        diagnostics: List[BaseDiagnostics] = [
            ExternalResourcesDiagnostics(device_type, device, self.logger, self.args, self.config),
            HttpAuthenticationDiagnostics(device_type, device, self.logger, self.args, self.config),
            HttpSecurityDiagnostics(device_type, device, self.logger, self.args, self.config),
            SnmpSecurityDiagnostics(device_type, device, self.logger, self.args, self.config),
        ]

        # Mapping of device types to their corresponding diagnostic classes
        device_type_mapping: Dict[str, Type[BaseDiagnostics]] = {
            "Router": RouterDiagnostics,
            "Switch": RouterDiagnostics,
            "Printer": PrinterDiagnostics,
            "Phone": PhoneDiagnostics,
            "Smart": SmartDiagnostics,
            "Game": GameDiagnostics,
            "Computer": ComputerDiagnostics,
        }

        # Retrieve the diagnostic class based on device_type, defaulting to OtherDeviceDiagnostics
        diagnostic_class = device_type_mapping.get(device_type, OtherDeviceDiagnostics)

        # Instantiate and add the device-specific diagnostic class
        diagnostics.append(diagnostic_class(device_type, device, self.logger, self.args, self.config))

        self.logger.debug(f"Diagnostics for device type '{device_type}': {[diag.__class__.__name__ for diag in diagnostics]}")

        return diagnostics

    def save_devices_to_file(self, classified_devices: Dict[str, List[Device]], filename: str) -> None:
        """
        Save the classified devices to a JSON file.
        """
        try:
            # Convert Device instances to dictionaries
            serializable_data = {
                device_type: [asdict(device) for device in devices]
                for device_type, devices in classified_devices.items()
            }

            with open(filename, 'w') as f:
                json.dump(serializable_data, f, indent=2)

            self.logger.info(f"Discovered devices saved to '{filename}'.")
        except Exception as e:
            self.logger.error(f"Failed to save devices to file: {e}")

    def _from_dict(self, cls: Type[DataclassType], data: Dict[str, Any]) -> DataclassType:
        """
        Recursively convert a dictionary to a dataclass instance.
        """
        if not is_dataclass(cls):
            return data  # Base case: not a dataclass

        fieldtypes = {f.name: f.type for f in fields(cls)}
        init_kwargs = {}
        for field_name, field_type in fieldtypes.items():
            if field_name not in data:
                continue  # Missing field; use default

            value = data[field_name]
            if value is None:
                init_kwargs[field_name] = None
                continue

            origin = get_origin(field_type)
            args = get_args(field_type)

            if origin is Union and type(None) in args:
                # It's an Optional field
                non_none_type = args[0] if args[1] == type(None) else args[1]
                if is_dataclass(non_none_type):
                    init_kwargs[field_name] = self._from_dict(non_none_type, value)
                else:
                    init_kwargs[field_name] = value
            elif origin is list:
                # It's a List field
                list_item_type = args[0]
                if is_dataclass(list_item_type):
                    init_kwargs[field_name] = [self._from_dict(list_item_type, item) for item in value]
                else:
                    init_kwargs[field_name] = value
            elif is_dataclass(field_type):
                # It's a nested dataclass
                init_kwargs[field_name] = self._from_dict(field_type, value)
            else:
                # It's a simple field
                init_kwargs[field_name] = value

        return cls(**init_kwargs)

    def load_devices_from_file(self, filename: str) -> Dict[str, List[Device]]:
        """
        Load the classified devices from a JSON file.
        """
        try:
            with open(filename, 'r') as f:
                data = json.load(f)

            classified_devices = {}
            for device_type, devices_list in data.items():
                classified_devices[device_type] = [
                    self._from_dict(Device, device_dict) for device_dict in devices_list
                ]

            if classified_devices:
                self.logger.info(f"Discovered devices loaded from '{filename}'.")
            else:
                classified_devices = {}
                self.logger.warning(f"No devices found in file '{filename}'.")

            return classified_devices
        except Exception as e:
            self.logger.error(f"Failed to load devices from file: {e}")
            return {}

    def display_devices(self, classified_devices: Dict[str, List[Device]]) -> None:
        """
        Display the classified devices in a tabular format.
        """
        for device_type, devices in classified_devices.items():
            title = f"{device_type.capitalize()}s"
            columns = ["Hostname", "IP Addresses", "MAC Address", "Vendor", "OS", "Open Ports"]
            rows = []
            for device in devices:
                hostname = ", ".join(device.hostnames) if device.hostnames else "N/A"
                ip_addresses = ", ".join(device.ip_addresses) if device.ip_addresses else "N/A"
                mac = device.mac_address if device.mac_address else "N/A"
                vendor = device.vendor if device.vendor else "Unknown"
                os_info = device.operating_system if device.operating_system else "Unknown"
                open_ports = ", ".join(
                    f"{port.port_id}/{port.protocol} {port.service.name if port.service and port.service.name else 'unknown'}"
                    for port in device.ports if port.service
                ) if device.ports else "N/A"
                rows.append([hostname, ip_addresses, mac, vendor, os_info, open_ports])
            self.print_table(title, columns, rows)


# Traffic Monitor Command
class TrafficMonitorCommand(BaseCommand):
    """
    Monitor network traffic to detect anomalies.
    """
    def __init__(self, args: argparse.Namespace, logger: logging.Logger, config: AppConfig):
        super().__init__(args, logger, config)

        # Initialize packet queue and processing thread
        self.packet_queue = queue.Queue()
        self.processing_thread = threading.Thread(target=self.process_packets, daemon=True)
        self.processing_thread.start()

        # Extract configurable thresholds from args or use defaults
        self.enable_arp_spoof = True  # Can be made configurable if needed
        self.enable_dhcp_flood = True
        self.enable_port_scan = True
        self.enable_dns_exfiltration = True
        self.enable_bandwidth_abuse = True
        self.enable_icmp_flood = True
        self.enable_syn_flood = True
        self.enable_malformed_packets = True
        self.enable_rogue_dhcp = True
        self.enable_http_abuse = True

        # Data structures for tracking anomalies using deque for efficient time window management
        self.arp_table = {}
        self.dhcp_requests = defaultdict(lambda: deque())
        self.port_scan_attempts = defaultdict(lambda: set())
        self.dns_queries = defaultdict(int)
        self.bandwidth_usage = defaultdict(int)
        self.icmp_requests = defaultdict(lambda: deque())
        self.syn_requests = defaultdict(lambda: deque())
        self.rogue_dhcp_servers = {}
        self.http_requests = defaultdict(int)
        self.malformed_packets = defaultdict(int)

        # Configuration for thresholds
        self.dhcp_threshold = args.dhcp_threshold
        self.port_scan_threshold = args.port_scan_threshold
        self.dns_exfil_threshold = args.dns_exfil_threshold
        self.bandwidth_threshold = args.bandwidth_threshold
        self.icmp_threshold = args.icmp_threshold
        self.syn_threshold = args.syn_threshold
        self.http_threshold = args.http_threshold
        self.malformed_threshold = args.malformed_threshold
        self.rogue_dhcp_threshold = args.rogue_dhcp_threshold

        # Time windows
        self.one_minute = timedelta(minutes=1)
        self.one_hour = timedelta(hours=1)

    def execute(self) -> None:
        """
        Execute traffic monitoring on the specified interface.
        """
        if not SCAPY_AVAILABLE:
            self.logger.error("Scapy is not installed. Install it using 'pip install scapy'.")
            sys.exit(1)

        interface = self.args.interface
        if not interface:
            self.logger.error("Network interface not specified. Use --interface to specify one.")
            sys.exit(1)

        self.logger.info(f"Starting traffic monitoring on interface {interface}... (Press Ctrl+C to stop)")

        try:
            sniff(iface=interface, prn=lambda pkt: self.packet_queue.put(pkt), store=False)
        except PermissionError:
            self.logger.error("Permission denied. Run the script with elevated privileges.")
            sys.exit(1)
        except KeyboardInterrupt:
            self.logger.info("Traffic monitoring stopped by user.")
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Error during traffic monitoring: {e}")
            sys.exit(1)

    def process_packets(self):
        """
        Continuously process packets from the queue.
        """
        while True:
            packet = self.packet_queue.get()
            try:
                self.process_packet(packet)
            except Exception as e:
                self.logger.error(f"Error processing packet: {e}")
            finally:
                self.packet_queue.task_done()

    def process_packet(self, packet):
        """
        Process each captured packet to detect various anomalies.
        """
        current_time = datetime.now()

        if self.enable_arp_spoof and packet.haslayer(ARP):
            self.detect_arp_spoofing(packet)

        if self.enable_dhcp_flood and packet.haslayer(DHCP):
            self.detect_dhcp_flood(packet, current_time)

        if self.enable_port_scan and packet.haslayer(TCP):
            self.detect_port_scan(packet)

        if self.enable_dns_exfiltration and packet.haslayer(DNS) and packet.getlayer(DNS).qr == 0:
            self.detect_dns_exfiltration(packet, current_time)

        if self.enable_bandwidth_abuse and packet.haslayer(IP):
            self.detect_bandwidth_abuse(packet, current_time)

        if self.enable_icmp_flood and packet.haslayer(ICMP):
            self.detect_icmp_flood(packet, current_time)

        if self.enable_syn_flood and packet.haslayer(TCP):
            self.detect_syn_flood(packet, current_time)

        if self.enable_malformed_packets:
            self.detect_malformed_packets(packet, current_time)

        if self.enable_rogue_dhcp and packet.haslayer(DHCP):
            self.detect_rogue_dhcp(packet, current_time)

        if self.enable_http_abuse and packet.haslayer(TCP) and packet.haslayer(Raw):
            self.detect_http_abuse(packet, current_time)

    def detect_arp_spoofing(self, packet):
        """
        Detect ARP spoofing by monitoring ARP replies.
        """
        arp = packet.getlayer(ARP)
        if arp.op == 2:  # is-at (response)
            sender_ip = arp.psrc
            sender_mac = arp.hwsrc
            if sender_ip in self.arp_table:
                if self.arp_table[sender_ip] != sender_mac:
                    alert = (f"ARP Spoofing detected! IP {sender_ip} is-at {sender_mac} "
                             f"(was {self.arp_table[sender_ip]})")
                    self.report_anomaly(alert)
            self.arp_table[sender_ip] = sender_mac

    def detect_dhcp_flood(self, packet, current_time):
        """
        Detect DHCP flood attacks by monitoring excessive DHCP requests.
        """
        dhcp = packet.getlayer(DHCP)
        client_mac = packet.getlayer(Ether).src

        # Record the timestamp of the DHCP request
        self.dhcp_requests[client_mac].append(current_time)

        # Remove requests older than 1 minute
        while self.dhcp_requests[client_mac] and self.dhcp_requests[client_mac][0] < current_time - self.one_minute:
            self.dhcp_requests[client_mac].popleft()

        if len(self.dhcp_requests[client_mac]) > self.dhcp_threshold:
            alert = (f"DHCP Flood detected from {client_mac}: "
                     f"{len(self.dhcp_requests[client_mac])} requests in the last minute.")
            self.report_anomaly(alert)
            self.dhcp_requests[client_mac].clear()

    def detect_port_scan(self, packet):
        """
        Detect port scanning by monitoring connections to multiple ports from the same IP.
        """
        ip_layer = packet.getlayer(IP)
        tcp_layer = packet.getlayer(TCP)
        src_ip = ip_layer.src
        dst_port = tcp_layer.dport

        self.port_scan_attempts[src_ip].add(dst_port)

        if len(self.port_scan_attempts[src_ip]) > self.port_scan_threshold:
            alert = (f"Port Scan detected from {src_ip}: "
                     f"Accessed {len(self.port_scan_attempts[src_ip])} unique ports.")
            self.report_anomaly(alert)
            # Reset after alert to prevent repeated alerts
            self.port_scan_attempts[src_ip].clear()

    def detect_dns_exfiltration(self, packet, current_time):
        """
        Detect DNS exfiltration by monitoring excessive DNS queries.
        """
        dns_layer = packet.getlayer(DNS)
        ip_layer = packet.getlayer(IP)
        src_ip = ip_layer.src

        # Record the DNS query
        self.dns_queries[src_ip] += 1

        # Remove counts older than 1 hour
        # For precise time window, consider using deque with timestamps
        # Here, resetting count periodically as a simplification
        if self.dns_queries[src_ip] > self.dns_exfil_threshold:
            alert = (f"DNS Exfiltration detected from {src_ip}: "
                     f"{self.dns_queries[src_ip]} DNS queries.")
            self.report_anomaly(alert)
            # Reset after alert
            self.dns_queries[src_ip] = 0

    def detect_bandwidth_abuse(self, packet, current_time):
        """
        Detect bandwidth abuse by monitoring data usage per client.
        """
        ip_layer = packet.getlayer(IP)
        src_ip = ip_layer.src
        packet_size = len(packet)

        self.bandwidth_usage[src_ip] += packet_size

        if self.bandwidth_usage[src_ip] > self.bandwidth_threshold:
            alert = (f"Bandwidth Abuse detected from {src_ip}: "
                     f"{self.bandwidth_usage[src_ip]} bytes in the last minute.")
            self.report_anomaly(alert)
            # Reset after alert
            self.bandwidth_usage[src_ip] = 0

    def detect_icmp_flood(self, packet, current_time):
        """
        Detect ICMP flood attacks by monitoring excessive ICMP requests.
        """
        src_ip = packet.getlayer(IP).src

        # Record the timestamp of the ICMP request
        self.icmp_requests[src_ip].append(current_time)

        # Remove requests older than 1 minute
        while self.icmp_requests[src_ip] and self.icmp_requests[src_ip][0] < current_time - self.one_minute:
            self.icmp_requests[src_ip].popleft()

        if len(self.icmp_requests[src_ip]) > self.icmp_threshold:
            alert = (f"ICMP Flood detected from {src_ip}: "
                     f"{len(self.icmp_requests[src_ip])} ICMP packets in the last minute.")
            self.report_anomaly(alert)

    def detect_syn_flood(self, packet, current_time):
        """
        Detect SYN flood attacks by monitoring excessive TCP SYN packets.
        """
        tcp_layer = packet.getlayer(TCP)
        if tcp_layer.flags & 0x02:  # SYN flag
            src_ip = packet.getlayer(IP).src

            # Record the timestamp of the SYN packet
            self.syn_requests[src_ip].append(current_time)

            # Remove SYNs older than 1 minute
            while self.syn_requests[src_ip] and self.syn_requests[src_ip][0] < current_time - self.one_minute:
                self.syn_requests[src_ip].popleft()

            if len(self.syn_requests[src_ip]) > self.syn_threshold:
                alert = (f"SYN Flood detected from {src_ip}: "
                         f"{len(self.syn_requests[src_ip])} SYN packets in the last minute.")
                self.report_anomaly(alert)
                # Reset after alert
                self.syn_requests[src_ip].clear()

    def detect_malformed_packets(self, packet, current_time):
        """
        Detect malformed packets that do not conform to protocol standards.
        """
        try:
            # Attempt to access packet layers to validate
            if packet.haslayer(IP):
                ip_layer = packet.getlayer(IP)
                if packet.haslayer(TCP):
                    tcp_layer = packet.getlayer(TCP)
                    _ = tcp_layer.flags  # Access a TCP field
                elif packet.haslayer(UDP):
                    udp_layer = packet.getlayer(UDP)
                    _ = udp_layer.sport  # Access a UDP field
        except Exception:
            src_ip = packet.getlayer(IP).src if packet.haslayer(IP) else "Unknown"
            self.malformed_packets[src_ip] += 1
            if self.malformed_packets[src_ip] > self.malformed_threshold:
                alert = (f"Malformed packets detected from {src_ip}: "
                         f"{self.malformed_packets[src_ip]} malformed packets.")
                self.report_anomaly(alert)
                # Reset after alert
                self.malformed_packets[src_ip] = 0

    def detect_rogue_dhcp(self, packet, current_time):
        """
        Detect rogue DHCP servers by monitoring DHCP OFFER messages.
        """
        dhcp = packet.getlayer(DHCP)
        if dhcp.options and any(option[0] == 'message-type' and option[1] == 2 for option in dhcp.options):
            # DHCP Offer
            server_ip = packet.getlayer(IP).src
            self.rogue_dhcp_servers[server_ip] = current_time

            # Remove entries older than 1 hour
            keys_to_remove = [ip for ip, ts in self.rogue_dhcp_servers.items() if ts < current_time - self.one_hour]
            for ip in keys_to_remove:
                del self.rogue_dhcp_servers[ip]

            if len(self.rogue_dhcp_servers) > self.rogue_dhcp_threshold:
                alert = f"Rogue DHCP Server detected: {server_ip}"
                self.report_anomaly(alert)
                # Reset after alert
                self.rogue_dhcp_servers.clear()

    def detect_http_abuse(self, packet, current_time):
        """
        Detect excessive HTTP requests that may indicate scraping or DoS.
        """
        src_ip = packet.getlayer(IP).src
        self.http_requests[src_ip] += 1

        # Reset periodically; precise time window handling can be added
        if self.http_requests[src_ip] > self.http_threshold:
            alert = (f"Excessive HTTP requests detected from {src_ip}: "
                     f"{self.http_requests[src_ip]} requests in the last minute.")
            self.report_anomaly(alert)
            # Reset after alert
            self.http_requests[src_ip] = 0

    def report_anomaly(self, message):
        """
        Report detected anomalies based on the verbosity level.
        """
        if RICH_AVAILABLE:
            console.print(message, style="bold red")
        else:
            print(message)


# System Information Command
class SystemInfoCommand(BaseCommand):
    """
    Gather and display system network information, including IPv4 and IPv6.
    """
    def execute(self) -> None:
        """
        Execute the system information gathering.
        """
        self.logger.info("Gathering system network information...")
        ip_info_v4 = self.get_ip_info('inet')
        ip_info_v6 = self.get_ip_info('inet6')
        routing_info_v4 = self.get_routing_info('inet')
        routing_info_v6 = self.get_routing_info('inet6')
        dns_info = self.get_dns_info()

        traceroute_info_v4 = None
        traceroute_info_v6 = None

        for traceroute_target in self.args.traceroute:
            if ':' in traceroute_target:
                traceroute_info_v6 = self.perform_traceroute(traceroute_target)
            else:
                traceroute_info_v4 = self.perform_traceroute(traceroute_target)

        self.display_system_info(ip_info_v4, ip_info_v6, routing_info_v4, routing_info_v6, dns_info, traceroute_info_v4, traceroute_info_v6)

    def get_ip_info(self, family: str = 'inet') -> str:
        """
        Retrieve IP configuration using the 'ip addr' command for the specified family.
        """
        self.logger.debug(f"Retrieving IP configuration for {family}...")
        try:
            if family == 'inet':
                cmd = ['ip', '-4', 'addr', 'show']
            elif family == 'inet6':
                cmd = ['ip', '-6', 'addr', 'show']
            else:
                self.logger.error(f"Unknown IP family: {family}")
                return ""

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            if family == 'inet6':
                self.logger.info("IPv6 is not supported on this system.")
            else:
                self.logger.error(f"Failed to get IP information for {family}: {e}")
            return ""

    def get_routing_info(self, family: str = 'inet') -> str:
        """
        Retrieve routing table using the 'ip route' command for the specified family.
        """
        self.logger.debug(f"Retrieving routing table for {family}...")
        try:
            if family == 'inet6':
                cmd = ['ip', '-6', 'route', 'show']
            else:
                cmd = ['ip', 'route', 'show']
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            if family == 'inet6':
                self.logger.info("IPv6 routing information is not available on this system.")
            else:
                self.logger.error(f"Failed to get routing information for {family}: {e}")
            return ""

    def get_dns_info(self) -> Dict[str, List[str]]:
        """
        Retrieve DNS server information, handling systemd-resolved if resolv.conf points to localhost.
        Returns a dictionary mapping network interfaces to their DNS servers for both IPv4 and IPv6.
        """
        self.logger.debug("Retrieving DNS servers...")
        dns_info = {}
        try:
            with open('/etc/resolv.conf', 'r') as f:
                resolv_conf_dns_v4 = []
                resolv_conf_dns_v6 = []
                for line in f:
                    if line.startswith('nameserver'):
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            dns_server = parts[1]
                            if re.match(r'^(\d{1,3}\.){3}\d{1,3}$', dns_server):
                                resolv_conf_dns_v4.append(dns_server)
                            elif re.match(r'^([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4}$', dns_server):
                                resolv_conf_dns_v6.append(dns_server)

                if resolv_conf_dns_v4:
                    dns_info['resolv.conf (IPv4)'] = resolv_conf_dns_v4
                    self.logger.debug(f"IPv4 DNS servers from resolv.conf: {resolv_conf_dns_v4}")
                if resolv_conf_dns_v6:
                    dns_info['resolv.conf (IPv6)'] = resolv_conf_dns_v6
                    self.logger.debug(f"IPv6 DNS servers from resolv.conf: {resolv_conf_dns_v6}")

                # Check if resolv.conf points to localhost for IPv4 or IPv6
                localhost_v4 = any(ns.startswith('127.') for ns in resolv_conf_dns_v4)
                localhost_v6 = any(ns.startswith('::1') for ns in resolv_conf_dns_v6)

                if localhost_v4 or localhost_v6:
                    self.logger.debug("resolv.conf points to localhost. Querying systemd-resolved for real DNS servers.")
                    try:
                        result = subprocess.run(['resolvectl', 'status'], capture_output=True, text=True, check=True)
                        # Use regex to find DNS servers for each interface
                        interface_pattern = re.compile(r'Link\s+\d+\s+\(([^)]+)\)')
                        dns_server_pattern = re.compile(r'DNS Servers:\s+(.+)')

                        current_iface = None
                        for line in result.stdout.splitlines():
                            iface_match = interface_pattern.match(line)
                            if iface_match:
                                current_iface = iface_match.group(1).strip()
                                self.logger.debug(f"Detected interface: {current_iface}")
                            else:
                                dns_match = dns_server_pattern.search(line)
                                if dns_match and current_iface:
                                    servers = dns_match.group(1).strip().split()
                                    ipv4_servers = [s for s in servers if re.match(r'^(\d{1,3}\.){3}\d{1,3}$', s)]
                                    ipv6_servers = [s for s in servers if
                                                    re.match(r'^([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4}$', s)]
                                    if ipv4_servers:
                                        dns_info.setdefault(f'{current_iface} (IPv4)', []).extend(ipv4_servers)
                                        self.logger.debug(f"Found IPv4 DNS servers for {current_iface}: {ipv4_servers}")
                                    if ipv6_servers:
                                        dns_info.setdefault(f'{current_iface} (IPv6)', []).extend(ipv6_servers)
                                        self.logger.debug(f"Found IPv6 DNS servers for {current_iface}: {ipv6_servers}")
                    except subprocess.CalledProcessError as e:
                        self.logger.info(f"Failed to run resolvectl: {e}")
                    except FileNotFoundError:
                        self.logger.info("resolvectl command not found. Ensure systemd-resolved is installed.")
        except Exception as e:
            self.logger.error(f"Failed to read DNS information: {e}")

        # Remove duplicates while preserving order for each interface
        for iface, servers in dns_info.items():
            seen = set()
            unique_servers = []
            for dns in servers:
                if dns not in seen:
                    seen.add(dns)
                    unique_servers.append(dns)
            dns_info[iface] = unique_servers

        return dns_info

    def perform_traceroute(self, target: str) -> Optional[str]:
        """
        Perform a traceroute to the specified target and return the output.
        """
        self.logger.info(f"Performing traceroute to {target}...")
        try:
            # Determine if target is IPv6 based on being enclosed in []
            if ':' in target:
                family = 'inet6'
                cmd = ['traceroute', '-n', '-6', target]
            else:
                family = 'inet'
                cmd = ['traceroute', '-n', target]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            self.logger.debug(f"Traceroute ({family}) completed successfully.")
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            if family == 'inet6' and 'Address family for hostname not supported' in error_msg:
                self.logger.info(f"Traceroute to {target} for {family} failed: IPv6 is not supported.")
            else:
                self.logger.info(f"Traceroute to {target} for {family} failed: {error_msg}")
        except FileNotFoundError:
            self.logger.info("traceroute command not found. Install it using your package manager.")
        except Exception as e:
            self.logger.error(f"Unexpected error during traceroute for {family}: {e}")
        return None

    def display_system_info(
            self,
            ip_info_v4: str,
            ip_info_v6: str,
            routing_info_v4: str,
            routing_info_v6: str,
            dns_info: Dict[str, List[str]],
            traceroute_info_v4: Optional[str],
            traceroute_info_v6: Optional[str]
    ) -> None:
        """
        Display the gathered system information for both IPv4 and IPv6.
        """
        if RICH_AVAILABLE:
            if ip_info_v4:
                console.print(Panel("[bold underline]Configuration (IPv4)[/bold underline]", style="cyan"))
                console.print(ip_info_v4)
            if ip_info_v6:
                console.print(Panel("[bold underline]Configuration (IPv6)[/bold underline]", style="cyan"))
                console.print(ip_info_v6)

            if routing_info_v4:
                console.print(Panel("[bold underline]Routing Table (IPv4)[/bold underline]", style="cyan"))
                console.print(routing_info_v4)
            if routing_info_v6:
                console.print(Panel("[bold underline]Routing Table (IPv6)[/bold underline]", style="cyan"))
                console.print(routing_info_v6)

            if dns_info:
                console.print(Panel("[bold underline]DNS Servers[/bold underline]", style="cyan"))
                for iface, dns_servers in dns_info.items():
                    console.print(f"[bold]{iface}:[/bold]")
                    for dns in dns_servers:
                        console.print(f"  - {dns}")

            if traceroute_info_v4:
                console.print(Panel("[bold underline]Traceroute (IPv4)[/bold underline]", style="cyan"))
                console.print(traceroute_info_v4)
            if traceroute_info_v6:
                console.print(Panel("[bold underline]Traceroute (IPv6)[/bold underline]", style="cyan"))
                console.print(traceroute_info_v6)
        else:
            if ip_info_v4:
                print("\n=== Configuration (IPv4) ===")
                print(ip_info_v4)
            if ip_info_v6:
                print("\n=== Configuration (IPv6) ===")
                print(ip_info_v6)

            if routing_info_v4:
                print("\n=== Routing Table (IPv4) ===")
                print(routing_info_v4)
            if routing_info_v6:
                print("\n=== Routing Table (IPv6) ===")
                print(routing_info_v6)

            if dns_info:
                print("\n=== DNS Servers ===")
                for iface, dns_servers in dns_info.items():
                    print(f"\n--- {iface} ---")
                    for dns in dns_servers:
                        print(f"- {dns}")

            if traceroute_info_v4:
                print("\n=== Traceroute (IPv4) ===")
                print(traceroute_info_v4)
            if traceroute_info_v6:
                print("\n=== Traceroute (IPv6) ===")
                print(traceroute_info_v6)


# Wifi Diagnostics Command
class WifiDiagnosticsCommand(BaseCommand):
    """
    Perform WiFi diagnostics and analyze available networks.
    """
    def execute(self) -> None:
        """
        Execute WiFi diagnostics.
        """
        self.logger.info("Starting WiFi diagnostics...")
        wifi_networks = self.scan_wifi_networks()
        if not wifi_networks:
            self.logger.error("No WiFi networks found.")
            sys.exit(1)

        target_networks = None
        if self.args.ssid:
            target_ssid = self.args.ssid
            self.logger.info(f"Performing diagnostics for SSID: {target_ssid}")
            target_networks = self.get_networks_by_ssid(wifi_networks, target_ssid)
            if not target_networks:
                self.logger.error(f"SSID '{target_ssid}' not found among available networks.")
                sys.exit(1)

        self.logger.info("Performing generic WiFi diagnostics.")
        issues = self.diagnose_wifi(wifi_networks, target_networks)

        self.display_issues(issues)

    def scan_wifi_networks(self) -> List[Dict[str, str]]:
        """
        Scan available WiFi networks using nmcli in terse mode for reliable parsing.
        """
        self.logger.debug("Scanning available WiFi networks using nmcli...")
        try:
            scan_command = ['nmcli', '-t', '-f', 'SSID,SIGNAL,CHAN,SECURITY', 'device', 'wifi', 'list', '--rescan', 'yes']
            if self.args.interface:
                scan_command.extend(['ifname', self.args.interface])
                self.logger.debug(f"Using interface: {self.args.interface}")
            result = subprocess.run(scan_command, capture_output=True, text=True, check=True)
            wifi_networks = self.parse_nmcli_output(result.stdout)
            self.logger.debug(f"Found {len(wifi_networks)} WiFi networks.")
            return wifi_networks
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to scan WiFi networks: {e}")
            return []
        except FileNotFoundError:
            self.logger.error("nmcli is not installed or not found in PATH.")
            return []

    def parse_nmcli_output(self, output: str) -> List[Dict[str, str]]:
        """
        Parse the output from nmcli in terse mode to handle SSIDs with colons and spaces.
        """
        networks = []
        lines = output.strip().split('\n')
        for line in lines:
            # Split only on the first three colons to handle SSIDs with colons
            parts = line.split(':', 3)
            if len(parts) < 4:
                continue  # Incomplete information
            ssid, signal, channel, security = parts[:4]
            networks.append({
                'SSID': ssid.strip(),
                'Signal': signal.strip(),
                'Channel': channel.strip(),
                'Security': security.strip()
            })
        return networks

    def get_networks_by_ssid(self, networks: List[Dict[str, str]], ssid: str) -> List[Dict[str, str]]:
        """
        Retrieve a specific network's details by its SSID.
        """
        target_networks = []
        for network in networks:
            if network['SSID'] == ssid:
                target_networks.append(network)
        return target_networks

    def diagnose_wifi(self, networks: List[Dict[str, str]], target_networks: List[Dict[str, str]] = None) -> List[WifiIssue]:
        """
        Perform generic diagnostics across all available WiFi networks.
        """
        issues = []

        if not target_networks:
            target_networks = networks

        # Extract unique channels from target_networks
        unique_channels = set()
        for net in target_networks:
            try:
                channel = int(net['Channel'])
                unique_channels.add(channel)
            except ValueError:
                self.logger.error(f"Invalid channel number for network '{net['SSID']}'. Skipping this network.")

        # Analyze each unique channel for interference
        unique_channels = sorted(unique_channels)
        for channel in unique_channels:
            channel_issue = self.analyze_channel_interference(channel, networks)
            if channel_issue:
                issues.append(channel_issue)

        # Check for open (unsecured) networks
        open_networks = [net for net in target_networks if net['Security'].upper() in ['OPEN', '--']]
        for net in open_networks:
            issues.append(WifiIssue(
                issue_type="Authentication",
                location=net['SSID'],
                description=f"Open and unsecured network on channel {net['Channel']}."
            ))

        # Check for networks with weak signals
        weak_networks = [net for net in target_networks if self.safe_int(net['Signal']) < self.args.signal_threshold]
        for net in weak_networks:
            issues.append(WifiIssue(
                issue_type="Signal",
                location=net['SSID'],
                description=f"Low signal strength: {net['Signal']}% on channel {net['Channel']}."
            ))

        return issues

    def analyze_channel_interference(self, channel: int, networks: List[Dict[str, str]]) -> Optional[WifiIssue]:
        """
        Analyze channel interference for a specific channel.
        """
        overlapping_channels = self.get_overlapping_channels(channel)
        count = 0
        for net in networks:
            try:
                net_channel = int(net['Channel'])
            except ValueError:
                continue
            if net_channel in overlapping_channels:
                count += 1
        if count > 3:  # Threshold for interference
            return WifiIssue(
                issue_type="Interference",
                location=f"Channel {channel}",
                description=f"High number of networks ({count}) on this channel causing interference."
            )
        return None

    def get_overlapping_channels(self, channel: int) -> List[int]:
        """
        Get overlapping channels for the 2.4GHz WiFi band.
        """
        # Define overlapping channels for 2.4GHz band
        overlapping = []
        if channel == 1:
            overlapping = [1, 2, 3]
        elif channel == 2:
            overlapping = [1, 2, 3, 4]
        elif channel == 3:
            overlapping = [1, 2, 3, 4, 5]
        elif channel == 4:
            overlapping = [2, 3, 4, 5, 6]
        elif channel == 5:
            overlapping = [3, 4, 5, 6, 7]
        elif channel == 6:
            overlapping = [4, 5, 6, 7, 8]
        elif channel == 7:
            overlapping = [5, 6, 7, 8, 9]
        elif channel == 8:
            overlapping = [6, 7, 8, 9, 10]
        elif channel == 9:
            overlapping = [7, 8, 9, 10, 11]
        elif channel == 10:
            overlapping = [8, 9, 10, 11, 12]
        elif channel == 11:
            overlapping = [9, 10, 11, 12, 13]
        elif channel == 12:
            overlapping = [10, 11, 12, 13, 14]
        elif channel == 13:
            overlapping = [11, 12, 13, 14]
        elif channel == 14:
            overlapping = [12, 13, 14]
        else:
            overlapping = [channel]
        return overlapping

    def display_issues(self, issues: List[WifiIssue]):
        """
        Display the identified WiFi diagnostic issues.
        """
        if not issues:
            self.logger.info("No WiFi issues detected.")
            return

        rows = [
            [
                issue.issue_type,
                issue.location,
                issue.description
            ]
            for issue in issues
        ]

        columns = ["Issue Type", "SSID/Channel", "Description"]
        self.print_table("WiFi Diagnostics Issues", columns, rows)

    def safe_int(self, value: str) -> int:
        """
        Safely convert a string to an integer, returning 0 on failure.
        """
        try:
            return int(value)
        except ValueError:
            return 0


class ContainerCommand(BaseCommand):
    def execute(self) -> None:
        macvlan_created: bool = False
        macvlan_iface_created: bool = False
        network_name: str = ''
        host_iface: str = ''
        try:
            # Define paths and image tag
            script_path: str = os.path.abspath(__file__)
            image_tag: str = 'diagnose-network'

            # Prepare the arguments
            if self.args.arguments and self.args.arguments[0] == '--':
                script_args: list = self.args.arguments[1:]
            else:
                script_args = self.args.arguments if self.args.arguments else ['-h']

            # Find the first non-option argument (command)
            command = next((arg for arg in script_args if not arg.startswith('-')), '')
            privileged_commands = {'system-info', 'si', 'wifi', 'wf', 'traffic-monitor', 'tm'}
            privileged = command in privileged_commands

            if command in ['container', 'co']:
                self.logger.error("... why? סּ_סּ")
                return

            # Determine the working directory
            if self.args.work_dir:
                work_dir_host: str = os.path.abspath(self.args.work_dir)
                if not os.path.exists(work_dir_host):
                    self.logger.error(f"Specified working directory does not exist: {work_dir_host}")
                    return
                self.logger.info(f"Using specified working directory: {work_dir_host}")
            else:
                work_dir_host = os.getcwd()
                self.logger.info(f"No working directory specified. Using current directory: {work_dir_host}")

            # Build the Docker image
            self._build_docker_image(image_tag)

            # Mount the script as read-only
            script_container_path: str = '/diagnose_network.py'
            mount_script: str = f"{script_path}:{script_container_path}:ro"

            # Mount the working directory
            work_dir_container: str = '/work_dir'
            mount_work_dir: str = f"{work_dir_host}:{work_dir_container}"

            # Prepare Docker run command
            run_cmd: list = [
                'docker', 'run',
                '--rm',
                '-it',
                '-v', mount_script,  # Mount script as read-only
                '-v', mount_work_dir,  # Mount working directory
                '-w', work_dir_container,  # Set working directory inside container
                '-v', '/var/run/docker.sock:/var/run/docker.sock',  # Mount Docker socket
            ]

            # Handle privileged mode
            if privileged:
                self.logger.info("Running container in privileged mode.")
                # Run the container in privileged mode
                run_cmd.append('--privileged')
                # Mount the D-Bus system bus socket
                if os.path.exists('/run/dbus/system_bus_socket'):
                    run_cmd.extend(['-v', '/run/dbus/system_bus_socket:/run/dbus/system_bus_socket'])
                # Mount /etc/machine-id
                if os.path.exists('/etc/machine-id'):
                    run_cmd.extend(['-v', '/etc/machine-id:/etc/machine-id:ro'])
                # Set environment variable for D-Bus system bus address
                run_cmd.extend(['-e', 'DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket'])

            # Handle network mode
            network_mode: str = self.args.network
            if network_mode == 'macvlan':
                network_name = 'diagnose_network_macvlan'
                parent_iface, subnet, gateway = self._detect_network_parameters()
                if not parent_iface or not subnet or not gateway:
                    self.logger.error("Failed to detect network parameters.")
                    raise RuntimeError("Network parameter detection failed.")
                host_iface = f"{parent_iface}.host"
                macvlan_created = self._setup_macvlan_network(network_name, parent_iface, subnet, gateway)
                if not macvlan_created:
                    self.logger.error("Failed to set up macvlan network.")
                    raise RuntimeError("Macvlan network setup failed.")
                macvlan_iface_created = self._setup_macvlan_interface(host_iface, parent_iface, subnet)
                if not macvlan_iface_created:
                    self.logger.error("Failed to set up macvlan interface.")
                    raise RuntimeError("Macvlan interface setup failed.")
                run_cmd.extend(['--network', network_name])
                self.logger.info(f"Attached container to macvlan network: {network_name}")
            elif network_mode == 'host':
                run_cmd.extend(['--network', 'host'])
                self.logger.info("Using host network mode.")
            elif network_mode == 'default':
                self.logger.info("Using default network mode.")
                # Do not add any --network parameter
            else:
                run_cmd.extend(['--network', network_mode])
                self.logger.info(f"Using network mode: {network_mode}")

            # Specify the image and command to run inside the container
            run_cmd.extend([
                image_tag,
                'python3', script_container_path,
            ] + script_args)

            self.logger.debug(f"Running command: {' '.join(run_cmd)}")
            subprocess.run(run_cmd, check=True)

        except subprocess.CalledProcessError as e:
            self.logger.error(f"An error occurred while running Docker: {e}")
        except Exception as e:
            self.logger.exception("An unexpected error occurred")
        finally:
            # Clean up macvlan interface and network if they were created
            if macvlan_iface_created:
                self._cleanup_macvlan_interface(host_iface)
            if macvlan_created:
                self._cleanup_macvlan_network(network_name)

    def _build_docker_image(self, image_tag: str) -> None:
        """
        Builds the Docker image using an embedded Dockerfile.
        """
        dockerfile: str = """
        FROM ubuntu:24.04
        RUN apt-get update && apt-get install -y \\
            sudo \\
            systemd \\
            dbus \\
            python3 \\
            python3-rich \\
            python3-bs4 \\
            python3-requests \\
            python3-psutil \\
            nmap \\
            nikto \\
            iproute2 \\
            docker.io \\
            traceroute \\
            network-manager \\
            && rm -rf /var/lib/apt/lists/*
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            dockerfile_path: str = os.path.join(temp_dir, 'Dockerfile')
            with open(dockerfile_path, 'w') as f:
                f.write(dockerfile)

            build_cmd: list = ['docker', 'build', '-t', image_tag, temp_dir]
            self.logger.debug(f"Running command: {' '.join(build_cmd)}")

            try:
                if self.args.debug:
                    # In debug mode, show the output
                    subprocess.run(build_cmd, check=True)
                else:
                    # In non-debug mode, suppress the output
                    subprocess.run(build_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                self.logger.info(f"Docker image '{image_tag}' built successfully.")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to build Docker image '{image_tag}': {e}")
                raise

    def _setup_macvlan_network(self, network_name: str, parent_iface: str, subnet: str, gateway: str) -> bool:
        """
        Sets up a macvlan network to allow the container to have its own network interface.
        Returns True if the network was created, False otherwise.
        """
        try:
            # Remove any existing network with the same name
            subprocess.run(
                ['docker', 'network', 'rm', network_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Create the macvlan network
            create_network_cmd: list = [
                'docker', 'network', 'create', '-d', 'macvlan',
                '--subnet', subnet,
                '--gateway', gateway,
                '--opt', f'parent={parent_iface}',
                network_name
            ]
            self.logger.debug(f"Creating macvlan network with command: {' '.join(create_network_cmd)}")
            subprocess.run(create_network_cmd, check=True)
            self.logger.info(f"Created macvlan network: {network_name}")
            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to set up macvlan network: {e}")
            return False
        except Exception as e:
            self.logger.exception("An unexpected error occurred during macvlan network setup.")
            return False

    def _cleanup_macvlan_network(self, network_name: str) -> None:
        """
        Cleans up the macvlan network created earlier.
        """
        try:
            subprocess.run(
                ['docker', 'network', 'rm', network_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            self.logger.info(f"Removed macvlan network: {network_name}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to remove macvlan network: {e}")
        except Exception as e:
            self.logger.exception("An unexpected error occurred during macvlan network cleanup.")

    def _setup_macvlan_interface(self, host_iface: str, parent_iface: str, subnet: str) -> bool:
        """
        Sets up a macvlan interface on the host.
        Returns True if the interface was created, False otherwise.
        """
        try:
            ip_address: Optional[str] = self._get_host_ip(subnet)
            if not ip_address:
                self.logger.error("Failed to calculate host IP for macvlan interface.")
                return False

            # Check if the interface already exists
            if self._interface_exists(host_iface):
                self.logger.info(f"Macvlan interface {host_iface} already exists. Skipping creation.")
                return True
            else:
                self.logger.debug(f"Creating macvlan interface on host: {host_iface} with IP {ip_address}")
                subprocess.run(
                    ['sudo', 'ip', 'link', 'add', host_iface, 'link',
                     parent_iface, 'type', 'macvlan', 'mode', 'bridge'],
                    check=True
                )
                subnet_prefix: str = subnet.split('/')[1]
                subprocess.run(['sudo', 'ip', 'addr', 'add', f'{ip_address}/{subnet_prefix}', 'dev', host_iface], check=True)
                subprocess.run(['sudo', 'ip', 'link', 'set', host_iface, 'up'], check=True)
                self.logger.info(f"Created macvlan interface on host: {host_iface}")
                return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to set up macvlan interface: {e}")
            return False
        except Exception as e:
            self.logger.exception("An unexpected error occurred during macvlan interface setup.")
            return False

    def _cleanup_macvlan_interface(self, host_iface: str) -> None:
        """
        Cleans up the macvlan interface created earlier.
        """
        try:
            subprocess.run(['sudo', 'ip', 'link', 'delete', host_iface], check=True)
            self.logger.info(f"Removed macvlan interface: {host_iface}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to remove macvlan interface: {e}")
        except Exception as e:
            self.logger.exception("An unexpected error occurred during macvlan interface cleanup.")

    def _interface_exists(self, interface_name: str) -> bool:
        """
        Checks if a network interface exists on the system.
        """
        try:
            result = subprocess.run(
                ['ip', 'link', 'show', interface_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.exception(f"Error checking if interface {interface_name} exists.")
            return False

    def _detect_network_parameters(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Automatically detects the parent network interface, subnet, and gateway.
        Returns a tuple (parent_interface, subnet, gateway).
        """
        try:
            # Determine the default gateway
            default_gateway: Optional[str] = self._get_default_gateway()

            if not default_gateway:
                self.logger.error("Unable to determine the default gateway.")
                return (None, None, None)

            # Determine the parent interface based on the default gateway
            parent_iface: Optional[str] = self._get_interface_for_gateway(default_gateway)

            if not parent_iface:
                self.logger.error("Unable to determine the parent interface for the default gateway.")
                return (None, None, None)

            # Get the subnet associated with the parent interface
            subnet: Optional[str] = self._get_subnet(parent_iface)

            if not subnet:
                self.logger.error(f"Unable to determine the subnet for interface {parent_iface}.")
                return (parent_iface, None, None)

            # Get the gateway IP
            gateway_ip: str = default_gateway

            self.logger.info(f"Detected parent interface: {parent_iface}")
            self.logger.info(f"Detected subnet: {subnet}")
            self.logger.info(f"Detected gateway: {gateway_ip}")

            return (parent_iface, subnet, gateway_ip)

        except Exception as e:
            self.logger.exception("Error while detecting network parameters.")
            return (None, None, None)

    def _get_default_gateway(self) -> Optional[str]:
        """
        Retrieves the default gateway using the system's routing table.
        """
        try:
            result = subprocess.run(['ip', 'route', 'show', 'default'], stdout=subprocess.PIPE, text=True)
            output: str = result.stdout.strip()
            if not output:
                self.logger.error("No default route found.")
                return None
            # Example output: "default via 192.168.1.1 dev eth0"
            parts: list = output.split()
            if 'via' in parts and 'dev' in parts:
                via_index: int = parts.index('via') + 1
                gateway: str = parts[via_index]
                return gateway
            else:
                self.logger.error("Unexpected format of default route.")
                return None
        except Exception as e:
            self.logger.exception("Failed to retrieve the default gateway.")
            return None

    def _get_interface_for_gateway(self, gateway: str) -> Optional[str]:
        """
        Determines the network interface associated with the given gateway IP.
        """
        try:
            # Use `ip route get` to find the interface
            result = subprocess.run(['ip', 'route', 'get', gateway], stdout=subprocess.PIPE, text=True)
            output: str = result.stdout.strip()
            if not output:
                self.logger.error("No route found for the gateway.")
                return None
            # Example output: "192.168.1.1 via 192.168.1.1 dev eth0 src 192.168.1.100 uid 1000"
            parts: list = output.split()
            if 'dev' in parts:
                dev_index: int = parts.index('dev') + 1
                iface: str = parts[dev_index]
                return iface
            else:
                self.logger.error("Unable to find interface in route output.")
                return None
        except Exception as e:
            self.logger.exception("Failed to determine the interface for the gateway.")
            return None

    def _get_subnet(self, interface: str) -> Optional[str]:
        """
        Retrieves the subnet for the given network interface.
        """
        try:
            result = subprocess.run(['ip', 'addr', 'show', interface], stdout=subprocess.PIPE, text=True)
            output: str = result.stdout.strip()
            if not output:
                self.logger.error(f"No information found for interface {interface}.")
                return None
            # Look for the line containing 'inet ' to find the subnet
            for line in output.split('\n'):
                line = line.strip()
                if line.startswith('inet '):
                    # Example: "inet 192.168.1.100/24 brd 192.168.1.255 scope global dynamic eth0"
                    parts: list = line.split()
                    inet: str = parts[1]  # '192.168.1.100/24'
                    # Use ipaddress module to get the network
                    ip_interface = ipaddress.ip_interface(inet)
                    network = ip_interface.network
                    return str(network)
            self.logger.error(f"No inet information found for interface {interface}.")
            return None
        except Exception as e:
            self.logger.exception(f"Failed to retrieve subnet for interface {interface}.")
            return None

    def _get_host_ip(self, subnet: str) -> Optional[str]:
        """
        Calculates an IP address for the host's macvlan interface within the subnet.
        """
        try:
            network = ipaddress.ip_network(subnet, strict=False)
            # Exclude network address and broadcast address
            hosts = list(network.hosts())
            if len(hosts) < 2:
                self.logger.error("Not enough IP addresses in the subnet.")
                return None
            # Assign the second IP address to the host's macvlan interface
            host_ip: str = str(hosts[1])
            return host_ip
        except Exception as e:
            self.logger.exception("Failed to calculate host IP for macvlan interface.")
            return None


# Argument Parser Setup
def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Advanced Network Diagnostic Tool",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Global options
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging (INFO level).'
    )
    parser.add_argument(
        '-vv', '--debug',
        action='store_true',
        help='Enable debug logging (DEBUG level).'
    )

    subparsers = parser.add_subparsers(dest='command', required=True, help='Sub-commands')

    # Subparser for system-info
    sys_info_parser = subparsers.add_parser(
        'system-info',
        aliases=['si'],
        help='Display detailed network information about the system.',
        description=(
            "Gather and display comprehensive network details of the host system, "
            "including interface configurations, routing tables, and more."
        )
    )
    sys_info_parser.add_argument(
        '--traceroute', '-t',
        type=str,
        nargs='*',
        default=['8.8.8.8', '2001:4860:4860::8888'],
        help='Perform a traceroute to the specified target.'
    )

    # Subparser for diagnose
    diagnose_parser = subparsers.add_parser(
        'diagnose',
        aliases=['dg'],
        help='Perform automated diagnostics on the network.',
        description=(
            "Execute a suite of diagnostic tools to assess the health and security of the network. "
            "Includes scanning for vulnerabilities, checking default credentials, and more."
        )
    )
    diagnose_parser.add_argument(
        '--virtual', '-V',
        action='store_true',
        help='Enable virtual interfaces in network scanning.'
    )
    diagnose_parser.add_argument(
        '--ipv6', '-6',
        action='store_true',
        help='Enable IPv6 in network scanning.'
    )
    diagnose_parser.add_argument(
        '--discovery', '-d',
        action='store_true',
        help='Perform network discovery to find devices only.'
    )
    diagnose_parser.add_argument(
        '--output-file', '-o',
        type=str,
        help='File to store discovered devices.'
    )
    diagnose_parser.add_argument(
        '--input-file', '-i',
        type=str,
        help='File to load discovered devices.'
    )
    diagnose_parser.add_argument(
        '--execution', '-e',
        type=ExecutionMode,
        choices=[mode.value for mode in ExecutionMode],
        default=ExecutionMode.DOCKER,
        help='Execution mode for scanning tools.'
    )
    diagnose_parser.add_argument(
        '--nikto', '-N',
        action='store_true',
        help='Run Nikto web server scanner on discovered devices.'
    )
    diagnose_parser.add_argument(
        '--golismero', '-G',
        action='store_true',
        help='Run Golismero automated scanning on discovered devices.'
    )
    diagnose_parser.add_argument(
        '--credentials', '-C',
        action='store_true',
        help='Check for default credentials on discovered devices.'
    )
    diagnose_parser.add_argument(
        '--all', '-A',
        action='store_true',
        help='Run all available diagnostic tools.'
    )

    # Subparser for traffic-monitor
    traffic_monitor_parser = subparsers.add_parser(
        'traffic-monitor',
        aliases=['tm'],
        help='Monitor network traffic to detect anomalies using Scapy.',
        description=(
            "Continuously monitor network traffic to identify and alert on suspicious activities "
            "such as DHCP floods, port scans, DNS exfiltration, and more."
        )
    )
    traffic_monitor_parser.add_argument(
        '--interface', '-i',
        type=str,
        required=True,
        help='Network interface to monitor (e.g., wlan0, eth0).'
    )
    # Traffic Monitor Command Options
    traffic_monitor_parser.add_argument(
        '--dhcp-threshold',
        type=int,
        default=100,
        help='Set DHCP flood threshold (default: 100).'
    )
    traffic_monitor_parser.add_argument(
        '--port-scan-threshold',
        type=int,
        default=50,
        help='Set port scan threshold (default: 50).'
    )
    traffic_monitor_parser.add_argument(
        '--dns-exfil-threshold',
        type=int,
        default=1000,
        help='Set DNS exfiltration threshold (default: 1000).'
    )
    traffic_monitor_parser.add_argument(
        '--bandwidth-threshold',
        type=int,
        default=1000000,
        help='Set bandwidth abuse threshold in bytes per minute (default: 1000000).'
    )
    traffic_monitor_parser.add_argument(
        '--icmp-threshold',
        type=int,
        default=500,
        help='Set ICMP flood threshold (default: 500).'
    )
    traffic_monitor_parser.add_argument(
        '--syn-threshold',
        type=int,
        default=1000,
        help='Set SYN flood threshold (default: 1000).'
    )
    traffic_monitor_parser.add_argument(
        '--http-threshold',
        type=int,
        default=1000,
        help='Set HTTP abuse threshold (default: 1000).'
    )
    traffic_monitor_parser.add_argument(
        '--malformed-threshold',
        type=int,
        default=50,
        help='Set malformed packets threshold (default: 50).'
    )
    traffic_monitor_parser.add_argument(
        '--rogue-dhcp-threshold',
        type=int,
        default=1,
        help='Set rogue DHCP server threshold (default: 1).'
    )

    # Subparser for wifi diagnostics
    wifi_parser = subparsers.add_parser(
        'wifi',
        aliases=['wf'],
        help='Perform WiFi diagnostics and analyze available networks.',
        description=(
            "Analyze WiFi networks to assess signal strength, detect rogue access points, and "
            "perform targeted diagnostics on specified SSIDs."
        )
    )
    wifi_parser.add_argument(
        '--ssid', '-s',
        type=str,
        required=False,
        help='Specify the SSID to perform targeted diagnostics.'
    )
    wifi_parser.add_argument(
        '--interface', '-i',
        type=str,
        required=False,
        help='Network interface to scan (e.g., wlan0, wlp3s0).'
    )
    wifi_parser.add_argument(
        '--signal-threshold', '-m',
        type=int,
        default=50,
        help='Minimum signal strength threshold (default: 50).'
    )

    # Subparser for container
    container_parser = subparsers.add_parser(
        'container',
        aliases=['co'],
        help='Run the script inside of a Docker container.',
        description=(
            "Execute the network diagnostic tool within a Docker container, allowing for isolated and "
            "consistent environments. Customize network settings and mount directories as needed."
        )
    )
    container_parser.add_argument(
        '-n', '--network',
        choices=['bridge', 'host', 'macvlan', 'default'],
        default='host',
        help='Specify the Docker network mode.'
    )
    container_parser.add_argument(
        '-w', '--work-dir',
        default='.',
        help='Specify the working directory to mount into the container.'
    )
    container_parser.add_argument(
        'arguments',
        nargs=argparse.REMAINDER,
        help='Arguments to pass to the script inside the container.'
    )

    return parser.parse_args()


# Logging Setup
def setup_logging(verbose: bool = False, debug: bool = False) -> logging.Logger:
    """
    Set up the logging configuration.
    """
    logger = logging.getLogger("diagnose_network")
    logger.setLevel(logging.DEBUG)  # Set to lowest level; handlers will filter

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')

    # Console handler
    if RICH_AVAILABLE:
        handler = RichHandler(rich_tracebacks=True)
        if debug:
            handler.setLevel(logging.DEBUG)
        elif verbose:
            handler.setLevel(logging.INFO)
        else:
            handler.setLevel(logging.WARNING)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        # Fallback to standard StreamHandler
        ch = logging.StreamHandler()
        if debug:
            ch.setLevel(logging.DEBUG)
        elif verbose:
            ch.setLevel(logging.INFO)
        else:
            ch.setLevel(logging.WARNING)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger


# Command Handler Mapping
COMMAND_CLASSES = {
    'system-info': SystemInfoCommand,
    'si': SystemInfoCommand,
    'diagnose': DiagnosticsCommand,
    'dg': DiagnosticsCommand,
    'traffic-monitor': TrafficMonitorCommand,
    'tm': TrafficMonitorCommand,
    'wifi': WifiDiagnosticsCommand,
    'wf': WifiDiagnosticsCommand,
    'container': ContainerCommand,
    'co': ContainerCommand,
}


# Main Function
def main() -> None:
    """
    Main function to orchestrate the network diagnostic process.
    """
    args = parse_arguments()
    logger = setup_logging(verbose=args.verbose, debug=args.debug)
    config = AppConfig()

    if not RICH_AVAILABLE:
        logger.warning("Rich library not found. Install it using 'pip install rich' for better output formatting. Really recommended.")

    # Instantiate and execute the appropriate command
    command_class = COMMAND_CLASSES.get(args.command)
    if not command_class:
        logger.error(f"Unknown command: {args.command}")
        sys.exit(1)

    command = command_class(args, logger, config)
    command.execute()

    logger.info("Network diagnostics completed successfully.")


if __name__ == "__main__":
    main()

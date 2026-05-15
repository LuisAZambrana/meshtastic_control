
# backend/mesh.py config generales

import time

import meshtastic.serial_interface

from pubsub import pub
from datetime import datetime

from serial.tools import list_ports


class MeshBackend:

    def __init__(self):

        self.interface = None
        self.connected = False

        self.current_port = None

        self.message_callback = None

    # =====================================================
    # LIST SERIAL PORTS
    # =====================================================

    def list_ports(self):

        ports = []

        try:

            detected_ports = list_ports.comports()

            for port in detected_ports:

                ports.append(port.device)

        except Exception as e:

            print(f"Port scan error: {e}")

        return sorted(ports)

    # =====================================================
    # CONNECT
    # =====================================================

    def connect(self, port):

        try:

            if self.interface:

                try:
                    self.interface.close()

                except:
                    pass

            self.interface = meshtastic.serial_interface.SerialInterface(
                devPath=port
            )

            self.connected = True

            self.current_port = port

            pub.subscribe(
                self.on_receive,
                "meshtastic.receive"
            )

            return True

        except Exception as e:

            print(f"Connection error: {e}")

            self.connected = False

            return False

    # =====================================================
    # CALLBACK
    # =====================================================

    def set_message_callback(self, callback):

        self.message_callback = callback

    # =====================================================
    # RECEIVE
    # =====================================================

    def on_receive(self, packet, interface):

        try:

            decoded = packet.get("decoded", {})

            portnum = decoded.get("portnum")

            if portnum != "TEXT_MESSAGE_APP":
                return

            text = decoded.get("text", "")

            from_id = packet.get("fromId", "Unknown")
            to_id = packet.get("toId", "^all")

            nodes = self.interface.nodes

            sender = {
                "id": from_id,
                "name": from_id
            }

            if from_id in nodes:

                user = nodes[from_id].get("user", {})

                sender = {
                    "id": from_id,
                    "name": user.get(
                        "longName",
                        from_id
                    )
                }

            timestamp = datetime.now().strftime("%H:%M:%S")

            is_dm = to_id != "^all"

            if self.message_callback:

                self.message_callback(
                    timestamp,
                    sender,
                    text,
                    is_dm
                )

        except Exception as e:

            print("RX ERROR:")
            print(str(e))

    # =====================================================
    # SEND CHANNEL
    # =====================================================

    def send_channel_message(self, message):

        if not self.connected:
            return False, "Not connected"

        try:

            self.interface.sendText(
                text=message
            )

            return True, "Sent"

        except Exception as e:

            return False, str(e)

    # =====================================================
    # SEND DM
    # =====================================================

    def send_direct_message(self, node, message):

        if not self.connected:
            return False, "Not connected"

        try:

            self.interface.sendText(
                text=message,
                destinationId=node["id"],
                wantAck=True
            )

            return True, "DM sent"

        except Exception as e:

            print("DM ERROR:")
            print(str(e))

            return False, str(e)

    # =====================================================
    # NODES
    # =====================================================

    def get_nodes(self, show_all=False):

        if not self.connected:
            return []

        result = []

        now = time.time()

        nodes = self.interface.nodes

        for node_id, node in nodes.items():

            last_heard = node.get("lastHeard", 0)

            seconds_ago = now - last_heard

            connected = seconds_ago < 900

            if not show_all and not connected:
                continue

            user = node.get("user", {})

            result.append({
                "id": user.get("id", "unknown"),
                "num": node.get("num", 0),
                "long_name": user.get("longName", "Unknown"),
                "short_name": user.get("shortName", ""),
                "hw": user.get("hwModel", ""),
                "snr": node.get("snr", "?"),
                "hops": node.get("hopsAway", "?"),
                "connected": connected,
            })

        return result

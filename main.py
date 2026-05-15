from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    Input,
    RichLog,
    ListView,
    ListItem,
    Label,
    TabbedContent,
    TabPane,
    Button,
)
from textual.screen import ModalScreen
from textual.binding import Binding

from backend.mesh import MeshBackend


class DMModal(ModalScreen):
    """Modal para enviar DM a un nodo seleccionado"""

    CSS = """
    #dm_dialog {
        width: 60;
        height: 10;
        padding: 1;
        border: round magenta;
        background: black;
    }
    """

    def __init__(self, node):
        super().__init__()
        self.node = node

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(
                f"Direct Message\n\n"
                f"To: {self.node['long_name']}"
            ),
            Input(
                placeholder="Write DM and press ENTER...",
                id="dm_input"
            ),
            id="dm_dialog"
        )

    def on_mount(self):
        self.query_one("#dm_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        message = event.value.strip()
        if not message:
            return
        self.dismiss({
            "node": self.node,
            "message": message
        })


class PresetModal(ModalScreen):
    """Modal para seleccionar preset LoRa"""

    CSS = """
    #preset_dialog {
        width: 50;
        height: 14;
        border: round cyan;
        background: black;
        padding: 1;
    }
    #preset_list {
        height: 100%;
    }
    """

    def __init__(self, presets):
        super().__init__()
        self.presets = presets

    def compose(self) -> ComposeResult:
        items = []
        for preset in self.presets:
            items.append(ListItem(Label(preset)))
        yield Vertical(
            Label("LoRa Presets"),
            ListView(*items, id="preset_list"),
            id="preset_dialog"
        )

    def on_mount(self):
        self.query_one("#preset_list").focus()

    def on_list_view_selected(self, event):
        index = event.list_view.index
        if index < 0:
            return
        selected = self.presets[index]
        self.dismiss(selected)


class PrivateChat(RichLog):
    """Widget para chat privado con un nodo específico"""

    def __init__(self, node_id, node_name, **kwargs):
        super().__init__(**kwargs)
        self.node_id = node_id
        self.node_name = node_name
        self.border_title = f"DM with {node_name}"

    def add_message(self, sender, message, timestamp, is_me=False):
        """Agrega un mensaje al chat"""
        if is_me:
            self.write(f"[{timestamp}] YOU -> {self.node_name}: {message}")
        else:
            self.write(f"[{timestamp}] {sender}: {message}")


class ChatPanel(RichLog):
    """Chat de canal público"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "CHANNEL CHAT (Primary)"

    def add_message(self, sender, message, timestamp, is_me=False):
        """Agrega un mensaje al chat de canal"""
        if is_me:
            self.write(f"[{timestamp}] YOU -> CHANNEL: {message}")
        else:
            self.write(f"[{timestamp}] {sender}: {message}")


class StatusPanel(RichLog):
    """Panel de estado"""
    pass


class MeshControl(App):
    """Aplicación principal"""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 30%;
        border: solid green;
    }

    #right {
        width: 70%;
        border: solid cyan;
    }

    #status {
        height: 8;
        border: solid yellow;
    }

    #input-area {
        dock: bottom;
        height: 3;
        padding: 0;
    }

    #input {
        width: 1fr;
    }

    #close-tab-btn {
        width: 5;
        height: 3;
        background: $error;
    }

    ListView {
        height: 100%;
    }

    TabbedContent {
        height: 100%;
    }

    TabPane {
        padding: 0;
    }

    .chat-container {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f3", "toggle_nodes", "Filter"),
        Binding("f4", "preset_popup", "Preset"),
        Binding("ctrl+c", "close_tab", "Close Tab"),
        Binding("ctrl+n", "new_tab", "New DM"),
        Binding("f10", "quit", "Exit"),
    ]

    def __init__(self):
        super().__init__()
        self.mesh = MeshBackend()
        self.nodes_cache = []
        self.channels = ["Primary"]
        self.active_channel = "Primary"
        self.ports = []
        self.show_all_nodes = False
        self.presets = [
            "Medium Fast",
            "Long Fast",
            "Long Slow",
            "Very Long Slow",
        ]
        self.current_preset = "Medium Fast"

        # Diccionario de chats privados: node_id -> TabPane id
        self.private_chats = {}
        self.active_tab_id = None
        self.next_tab_num = 1  # Para generar IDs únicos

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            with Vertical(id="left"):
                self.sidebar = ListView(id="sidebar")
                yield self.sidebar

            with Vertical(id="right"):
                self.tabs = TabbedContent(id="chat-tabs")
                yield self.tabs

        self.status = StatusPanel(markup=False, id="status")
        yield self.status

        with Horizontal(id="input-area"):
            self.message_input = Input(
                placeholder="Type message and press ENTER... (Channel mode)",
                id="input"
            )
            yield self.message_input
            self.close_btn = Button(" Close Tab", id="close-tab-btn")
            yield self.close_btn

        yield Footer()

    def on_mount(self):
        """Inicialización al montar la app"""
        # Crear tab de canal principal
        self.channel_chat = ChatPanel(markup=False)
        self.tabs.add_pane(TabPane(" Channel", self.channel_chat, id="channel-tab"))

        self.channel_chat.write("Meshtastic Control by surc.ar")
        self.channel_chat.write("Mesh Operations Console - IRC Style")
        self.channel_chat.write("")
        self.channel_chat.write("Select interface from left panel")
        self.channel_chat.write("")
        self.channel_chat.write("Commands:")
        self.channel_chat.write("   - Click on a node -> Open private chat")
        self.channel_chat.write("   - Ctrl+C -> Close current tab")
        self.channel_chat.write("   - F3 -> Toggle node filter")
        self.channel_chat.write("   - F4 -> Change LoRa preset")

        self.mesh.set_message_callback(self.receive_message)
        self.load_sidebar()

    def _sanitize_id(self, node_id):
        """Limpia el node_id para usarlo como ID válido en Textual"""
        # Reemplazar caracteres no válidos por guiones bajos
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', node_id)
        # Asegurar que no empiece con número
        if sanitized and sanitized[0].isdigit():
            sanitized = f"n{sanitized}"
        return sanitized

    def load_sidebar(self):
        """Carga la barra lateral con interfaces, canales y nodos"""
        self.sidebar.clear()

        # Interfaces
        self.sidebar.append(ListItem(Label("=== INTERFACES ===")))
        self.ports = self.mesh.list_ports()
        for port in self.ports:
            active = ">> " if port == self.mesh.current_port else "   "
            self.sidebar.append(ListItem(Label(f"{active}{port}")))

        # Canales
        self.sidebar.append(ListItem(Label("")))
        self.sidebar.append(ListItem(Label("=== CHANNELS ===")))
        for channel in self.channels:
            prefix = ">> " if channel == self.active_channel else "   "
            self.sidebar.append(ListItem(Label(f"{prefix}# {channel}")))

        # Nodos
        self.sidebar.append(ListItem(Label("")))
        mode = "CONNECTED ONLY" if not self.show_all_nodes else "ALL"
        self.sidebar.append(ListItem(Label(f"=== NODES ({mode}) ===")))

        self.nodes_cache = self.mesh.get_nodes(self.show_all_nodes)
        for node in self.nodes_cache:
            dot = "[green]●[/]" if node["connected"] else "[red]○[/]"
            text = f"{dot} {node['long_name']}\n    {node['short_name']} | {node['hw']}"
            self.sidebar.append(ListItem(Label(text)))

    def receive_message(self, timestamp, sender, text, is_dm):
        """Callback para mensajes recibidos"""
        if is_dm:
            # Buscar si tenemos un chat abierto con este nodo
            node_id = self._find_node_id_by_name(sender)
            if node_id and node_id in self.private_chats:
                # Agregar al chat privado existente
                chat_widget = self.private_chats[node_id]["widget"]
                chat_widget.add_message(sender, text, timestamp, is_me=False)
                # Notificar si no es el tab activo
                if self.tabs.active != self.private_chats[node_id]["tab_id"]:
                    self.status.write(f"[DM from {sender}] {text[:50]}...")
            else:
                # Si no hay chat abierto, mostrar en canal
                self.channel_chat.add_message(sender, text, timestamp, is_me=False)
                self.status.write(f"[DM from {sender}] {text[:50]}...")
        else:
            # Mensaje de canal
            self.channel_chat.add_message(sender, text, timestamp, is_me=False)

    def _find_node_id_by_name(self, long_name):
        """Busca node_id por nombre largo"""
        for node in self.nodes_cache:
            if node["long_name"] == long_name:
                return node["id"]
        return None

    def open_private_chat(self, node):
        """Abre o enfoca un chat privado con un nodo"""
        node_id = node["id"]

        # Si ya existe, cambiar a ese tab
        if node_id in self.private_chats:
            self.tabs.active = self.private_chats[node_id]["tab_id"]
            return

        # Crear nuevo chat privado
        chat = PrivateChat(
            node_id,
            node["long_name"],
            markup=False
        )

        # Sanitizar ID para que sea válido en Textual
        safe_id = self._sanitize_id(node_id)
        tab_id = f"dm-tab-{safe_id}"
        tab_title = f" DM: {node['short_name']}"

        self.tabs.add_pane(TabPane(tab_title, chat, id=tab_id))
        self.private_chats[node_id] = {
            "widget": chat,
            "tab_id": tab_id,
            "node": node
        }

        # Cambiar al nuevo tab
        self.tabs.active = tab_id

        # Mensaje de bienvenida
        chat.write(f"--- Started private chat with {node['long_name']} ---")
        chat.write("")

        self.status.write(f"Opened private chat with {node['long_name']}")

    def close_current_tab(self):
        """Cierra el tab actual (si no es el canal principal)"""
        current_tab_id = self.tabs.active

        if current_tab_id == "channel-tab":
            self.status.write("Cannot close main channel tab")
            return

        # Buscar y eliminar el chat privado
        for node_id, data in list(self.private_chats.items()):
            if data["tab_id"] == current_tab_id:
                self.tabs.remove_pane(current_tab_id)
                del self.private_chats[node_id]
                self.status.write("Closed private chat")
                break

    def on_input_submitted(self, event: Input.Submitted):
        """Envía mensaje según el tab activo"""
        message = event.value.strip()
        if not message:
            return

        current_tab_id = self.tabs.active
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Determinar si es canal o DM
        if current_tab_id == "channel-tab":
            # Enviar al canal
            ok, response = self.mesh.send_channel_message(message)
            if ok:
                self.channel_chat.add_message("YOU", message, timestamp, is_me=True)
                self.status.write(f"Sent to channel | Preset: {self.current_preset}")
            else:
                self.status.write(f"ERROR: {response}")
        else:
            # Buscar nodo correspondiente al tab
            for node_id, data in self.private_chats.items():
                if data["tab_id"] == current_tab_id:
                    node = data["node"]
                    ok, response = self.mesh.send_direct_message(node, message)
                    if ok:
                        data["widget"].add_message("YOU", message, timestamp, is_me=True)
                        self.status.write(f"DM sent to {node['long_name']}")
                    else:
                        self.status.write(f"DM ERROR: {response}")
                    break

        event.input.value = ""

    def on_button_pressed(self, event: Button.Pressed):
        """Maneja botones"""
        if event.button.id == "close-tab-btn":
            self.close_current_tab()

    def on_list_view_selected(self, event):
        """Maneja selección en la barra lateral"""
        index = event.list_view.index

        if index == 0:
            return

        # Manejar selección de puerto
        if index <= len(self.ports):
            selected_port = self.ports[index - 1]
            self.status.write(f"Connecting to {selected_port}...")
            ok = self.mesh.connect(selected_port)
            if ok:
                self.channel_chat.write(f"Connected to {selected_port}")
                self.status.write(f"Radio connected | {self.current_preset}")
                self.load_sidebar()
            else:
                self.status.write("Connection failed")
            return

        # Calcular offset para nodos
        node_start = len(self.ports) + len(self.channels) + 5
        node_index = index - node_start

        if node_index < 0 or node_index >= len(self.nodes_cache):
            return

        selected_node = self.nodes_cache[node_index]

        # Abrir chat privado (estilo IRC)
        self.open_private_chat(selected_node)

    def dm_callback(self, result):
        """Callback del modal DM (mantenido por compatibilidad)"""
        if not result:
            return
        self.open_private_chat(result["node"])
        # Enviar mensaje después de abrir chat
        self.call_after_refresh(lambda: self._send_dm_after_open(result))

    def _send_dm_after_open(self, result):
        """Envía DM después de abrir el chat"""
        node = result["node"]
        message = result["message"]
        ok, response = self.mesh.send_direct_message(node, message)
        if ok:
            node_id = node["id"]
            if node_id in self.private_chats:
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.private_chats[node_id]["widget"].add_message("YOU", message, timestamp, is_me=True)
            self.status.write(f"DM sent to {node['long_name']}")
        else:
            self.status.write(f"DM ERROR: {response}")

    def preset_callback(self, result):
        """Callback para selección de preset"""
        if not result:
            return
        self.current_preset = result
        self.status.write(f"LoRa preset: {result}")

    def action_preset_popup(self):
        """Abre modal de presets"""
        self.push_screen(PresetModal(self.presets), callback=self.preset_callback)

    def action_toggle_nodes(self):
        """Toggle mostrar todos los nodos"""
        self.show_all_nodes = not self.show_all_nodes
        self.load_sidebar()

    def action_close_tab(self):
        """Cierra tab actual"""
        self.close_current_tab()

    def action_new_tab(self):
        """Nuevo DM (muestra modal)"""
        if self.nodes_cache:
            self.status.write("Click on a node in the sidebar to open a private chat")

    def action_help(self):
        """Muestra ayuda"""
        self.status.write("Help: Click node for private chat | F3=Filter nodes | F4=Preset | Ctrl+C=Close tab")


if __name__ == "__main__":
    app = MeshControl()
    app.run()
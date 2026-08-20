# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_song_time", "set_arrangement_loop", "jump_to_cue",
                                 "create_cue_point", "delete_cue_point",
                                 "create_arrangement_clip", "create_arrangement_audio_clip",
                                 "duplicate_to_arrangement", "delete_arrangement_clip",
                                 "set_arrangement_clip_property",
                                 "set_view", "control_arrangement_view",
                                 "manage_clip_automation",
                                 "add_notes_to_arrangement_clip",
                                 "set_device_parameter", "set_device_enabled",
                                 "delete_device", "navigate_preset",
                                 "delete_track",
                                 "set_track_volume", "set_track_panning",
                                 "clear_notes_from_clip", "delete_clip",
                                 "create_audio_track",
                                 "set_track_state", "set_send_level",
                                 "set_wavetable_property",
                                 "add_wavetable_mod_target",
                                 "set_wavetable_modulation",
                                 "set_clip_property",
                                 "fire_scene", "create_scene",
                                 "delete_scene", "duplicate_scene",
                                 "set_scene_property", "undo", "redo"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "add_notes_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_clip(track_index, clip_index, notes)
                        elif command_type == "set_clip_name":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            name = params.get("name", "")
                            result = self._set_clip_name(track_index, clip_index, name)
                        elif command_type == "set_tempo":
                            tempo = params.get("tempo", 120.0)
                            result = self._set_tempo(tempo)
                        elif command_type == "fire_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._fire_clip(track_index, clip_index)
                        elif command_type == "stop_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._stop_clip(track_index, clip_index)
                        elif command_type == "start_playback":
                            result = self._start_playback()
                        elif command_type == "stop_playback":
                            result = self._stop_playback()
                        elif command_type == "load_instrument_or_effect":
                            track_index = params.get("track_index", 0)
                            uri = params.get("uri", "")
                            result = self._load_instrument_or_effect(track_index, uri)
                        elif command_type == "load_browser_item":
                            track_index = params.get("track_index", 0)
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item(track_index, item_uri)
                        elif command_type == "set_song_time":
                            time_val = params.get("time", 0.0)
                            result = self._set_song_time(time_val)
                        elif command_type == "set_arrangement_loop":
                            enabled = params.get("enabled", True)
                            start = params.get("start", None)
                            length = params.get("length", None)
                            result = self._set_arrangement_loop(enabled, start, length)
                        elif command_type == "jump_to_cue":
                            direction = params.get("direction", None)
                            name = params.get("name", None)
                            result = self._jump_to_cue(direction, name)
                        elif command_type == "create_cue_point":
                            time_val = params.get("time", 0.0)
                            name = params.get("name", "")
                            result = self._create_cue_point(time_val, name)
                        elif command_type == "delete_cue_point":
                            time_val = params.get("time", 0.0)
                            result = self._delete_cue_point(time_val)
                        elif command_type == "create_arrangement_clip":
                            ti = params.get("track_index", 0)
                            pos = params.get("position", 0.0)
                            length = params.get("length", 4.0)
                            result = self._create_arrangement_clip(ti, pos, length)
                        elif command_type == "create_arrangement_audio_clip":
                            ti = params.get("track_index", 0)
                            pos = params.get("position", 0.0)
                            fp = params.get("file_path", "")
                            result = self._create_arrangement_audio_clip(ti, pos, fp)
                        elif command_type == "duplicate_to_arrangement":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            dt = params.get("destination_time", 0.0)
                            result = self._duplicate_to_arrangement(ti, ci, dt)
                        elif command_type == "delete_arrangement_clip":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", None)
                            cn = params.get("clip_name", None)
                            result = self._delete_arrangement_clip(ti, ci, cn)
                        elif command_type == "set_arrangement_clip_property":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            prop = params.get("property", "")
                            val = params.get("value", None)
                            result = self._set_arrangement_clip_property(ti, ci, prop, val)
                        elif command_type == "set_view":
                            vn = params.get("view_name", "Arranger")
                            result = self._set_view(vn)
                        elif command_type == "control_arrangement_view":
                            action = params.get("action", "")
                            ti = params.get("track_index", 0)
                            result = self._control_arrangement_view(action, ti)
                        elif command_type == "manage_clip_automation":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            action = params.get("action", "create")
                            pn = params.get("parameter_name", "")
                            result = self._manage_clip_automation(ti, ci, action, pn)
                        elif command_type == "add_notes_to_arrangement_clip":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_arrangement_clip(ti, ci, notes)
                        # Device modifying commands
                        elif command_type == "set_device_parameter":
                            ti = params.get("track_index", 0)
                            di = params.get("device_index", 0)
                            ci = params.get("chain_index", None)
                            pn = params.get("parameter_name", None)
                            pi = params.get("parameter_index", None)
                            val = params.get("value", 0.0)
                            result = self._set_device_parameter(ti, di, ci, pn, pi, val)
                        elif command_type == "set_device_enabled":
                            ti = params.get("track_index", 0)
                            di = params.get("device_index", 0)
                            ci = params.get("chain_index", None)
                            enabled = params.get("enabled", True)
                            result = self._set_device_enabled(ti, di, ci, enabled)
                        elif command_type == "delete_device":
                            ti = params.get("track_index", 0)
                            di = params.get("device_index", 0)
                            result = self._delete_device(ti, di)
                        elif command_type == "delete_track":
                            ti = params.get("track_index", 0)
                            result = self._delete_track(ti)
                        elif command_type == "set_track_volume":
                            ti = params.get("track_index", 0)
                            volume = params.get("volume", 0.85)
                            result = self._set_track_volume(ti, volume)
                        elif command_type == "set_track_panning":
                            ti = params.get("track_index", 0)
                            panning = params.get("panning", 0.0)
                            result = self._set_track_panning(ti, panning)
                        elif command_type == "navigate_preset":
                            ti = params.get("track_index", 0)
                            di = params.get("device_index", 0)
                            ci = params.get("chain_index", None)
                            direction = params.get("direction", "current")
                            result = self._navigate_preset(ti, di, ci, direction)

                        elif command_type == "clear_notes_from_clip":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            result = self._clear_notes_from_clip(ti, ci)
                        elif command_type == "delete_clip":
                            ti = params.get("track_index", 0)
                            ci = params.get("clip_index", 0)
                            result = self._delete_clip(ti, ci)
                        elif command_type == "create_audio_track":
                            idx = params.get("index", -1)
                            result = self._create_audio_track(idx)

                        elif command_type == "set_track_state":
                            ti = params.get("track_index", 0)
                            result = self._set_track_state(
                                ti,
                                params.get("mute", None),
                                params.get("solo", None),
                                params.get("arm", None))
                        elif command_type == "set_send_level":
                            ti = params.get("track_index", 0)
                            si = params.get("send_index", 0)
                            val = params.get("value", 0.0)
                            result = self._set_send_level(ti, si, val)

                        elif command_type == "set_wavetable_property":
                            result = self._set_wavetable_property(
                                params.get("track_index", 0),
                                params.get("device_index", 0),
                                params.get("chain_index", None),
                                params.get("name", ""),
                                params.get("value", 0))
                        elif command_type == "add_wavetable_mod_target":
                            result = self._add_wavetable_mod_target(
                                params.get("track_index", 0),
                                params.get("device_index", 0),
                                params.get("chain_index", None),
                                params.get("parameter_name", None),
                                params.get("parameter_index", None))
                        elif command_type == "set_wavetable_modulation":
                            result = self._set_wavetable_modulation(
                                params.get("track_index", 0),
                                params.get("device_index", 0),
                                params.get("chain_index", None),
                                params.get("target_index", 0),
                                params.get("source", "lfo_1"),
                                params.get("value", 0.0))

                        elif command_type == "set_clip_property":
                            result = self._set_clip_property(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("property_name", ""),
                                params.get("value", None))

                        elif command_type == "fire_scene":
                            result = self._fire_scene(params.get("scene_index", 0))
                        elif command_type == "create_scene":
                            result = self._create_scene(params.get("index", -1))
                        elif command_type == "delete_scene":
                            result = self._delete_scene(params.get("scene_index", 0))
                        elif command_type == "duplicate_scene":
                            result = self._duplicate_scene(
                                params.get("scene_index", 0))
                        elif command_type == "set_scene_property":
                            result = self._set_scene_property(
                                params.get("scene_index", 0),
                                params.get("property_name", ""),
                                params.get("value", None))
                        elif command_type == "undo":
                            result = self._undo()
                        elif command_type == "redo":
                            result = self._redo()

                        # Put the result in the queue
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_track_volume":
                ti = params.get("track_index", 0)
                response["result"] = self._get_track_volume(ti)
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            elif command_type == "get_arrangement_info":
                track_index = params.get("track_index", -1)
                response["result"] = self._get_arrangement_info(track_index)
            elif command_type == "get_cue_points":
                response["result"] = self._get_cue_points()
            # Device read-only commands
            elif command_type == "get_device_parameters":
                ti = params.get("track_index", 0)
                di = params.get("device_index", 0)
                ci = params.get("chain_index", None)
                show_all = params.get("show_all", False)
                response["result"] = self._get_device_parameters(ti, di, ci, show_all)
            elif command_type == "get_chain_info":
                ti = params.get("track_index", 0)
                di = params.get("device_index", 0)
                ci = params.get("chain_index", None)
                response["result"] = self._get_chain_info(ti, di, ci)
            elif command_type == "get_drum_pad_info":
                ti = params.get("track_index", 0)
                di = params.get("device_index", 0)
                response["result"] = self._get_drum_pad_info(ti, di)
            elif command_type == "get_clip_notes":
                ti = params.get("track_index", 0)
                ci = params.get("clip_index", 0)
                response["result"] = self._get_clip_notes(ti, ci)
            elif command_type == "get_session_snapshot":
                inc_n = params.get("include_notes", True)
                inc_p = params.get("include_params", True)
                response["result"] = self._get_session_snapshot(inc_n, inc_p)
            elif command_type == "describe_device_api":
                ti = params.get("track_index", 0)
                di = params.get("device_index", 0)
                ci = params.get("chain_index", None)
                response["result"] = self._describe_device_api(ti, di, ci)
            elif command_type == "get_wavetable_state":
                ti = params.get("track_index", 0)
                di = params.get("device_index", 0)
                ci = params.get("chain_index", None)
                response["result"] = self._get_wavetable_state(ti, di, ci)
            elif command_type == "get_clip_properties":
                ti = params.get("track_index", 0)
                ci = params.get("clip_index", 0)
                response["result"] = self._get_clip_properties(ti, ci)
            elif command_type == "get_scenes":
                response["result"] = self._get_scenes()
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
    # Arrangement helper methods

    def _get_arrangement_clip_info(self, clip):
        """Serialize a Clip object to ArrangementClipInfo dict."""
        try:
            return {
                "name": clip.name,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "length": clip.end_time - clip.start_time,
                "is_midi": clip.is_midi_clip,
                "is_audio": clip.is_audio_clip,
                "muted": clip.muted,
                "color": clip.color,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
            }
        except Exception as e:
            self.log_message("Error getting arrangement clip info: " + str(e))
            return {"name": "unknown", "error": str(e)}

    def _get_transport_info(self):
        """Serialize Song transport state to TransportInfo dict."""
        try:
            return {
                "is_playing": self._song.is_playing,
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "current_time": self._song.current_song_time,
                "song_length": self._song.song_length,
                "loop_enabled": self._song.loop,
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "arrangement_overdub": self._song.arrangement_overdub,
                "back_to_arranger": self._song.back_to_arranger,
            }
        except Exception as e:
            self.log_message("Error getting transport info: " + str(e))
            raise

    def _resolve_arrangement_clip(self, track_index, clip_index=None, clip_name=None):
        """Resolve an arrangement clip by index or name.

        Returns (track, clip) tuple.
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))

        track = self._song.tracks[track_index]
        clips = track.arrangement_clips

        if clip_name:
            matches = [(i, c) for i, c in enumerate(clips) if c.name == clip_name]
            if len(matches) == 0:
                raise ValueError("No arrangement clip named '{0}' on track '{1}'".format(
                    clip_name, track.name))
            if len(matches) > 1:
                raise ValueError("Ambiguous: {0} clips named '{1}' on track '{2}'".format(
                    len(matches), clip_name, track.name))
            return track, matches[0][1]

        if clip_index is None:
            raise ValueError("Either clip_index or clip_name must be provided")

        if clip_index < 0 or clip_index >= len(clips):
            raise IndexError("Clip index {0} out of range (0-{1}) on track '{2}'".format(
                clip_index, len(clips) - 1, track.name))

        return track, clips[clip_index]

    def _check_overlap(self, track, position, length):
        """Return list of clip names that overlap with [position, position+length)."""
        overlapped = []
        end = position + length
        for clip in track.arrangement_clips:
            if clip.start_time < end and clip.end_time > position:
                overlapped.append(clip.name or "(unnamed)")
        return overlapped

    # Command implementations

    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))

            track = all_tracks[track_index]

            # Get clip slots. Return and master tracks raise on access rather
            # than lacking the attribute, so a bare getattr default is not enough.
            try:
                _slots = list(track.clip_slots)
            except Exception:
                _slots = []
            clip_slots = []
            for slot_index, slot in enumerate(_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            is_group = bool(getattr(track, "is_foldable", False))

            # Same guard: touching .arm on a return/master track raises.
            arm_state = None
            if not is_group:
                try:
                    arm_state = track.arm
                except Exception:
                    arm_state = None

            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "is_group_track": is_group,
                "mute": track.mute,
                "solo": track.solo,
                "arm": arm_state,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "sends": self._safe_sends(track),
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise

    def _get_track_volume(self, track_index):
        """Get current volume and panning for a track's mixer fader."""
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            track = all_tracks[track_index]
            vol_param = track.mixer_device.volume
            pan_param = track.mixer_device.panning
            return {
                "track_name": track.name,
                "volume": vol_param.value,
                "volume_min": vol_param.min,
                "volume_max": vol_param.max,
                "panning": pan_param.value,
                "panning_min": pan_param.min,
                "panning_max": pan_param.max,
            }
        except Exception as e:
            self.log_message("Error getting track volume: " + str(e))
            raise

    def _set_track_volume(self, track_index, volume):
        """Set the mixer fader volume for a track.
        
        Args:
            track_index: 0-based track index (includes return tracks after session tracks)
            volume: normalized 0.0 (silence) to 1.0 (max). 0.85 = 0dB unity gain.
        """
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            track = all_tracks[track_index]
            vol_param = track.mixer_device.volume
            # Clamp to valid range
            clamped = max(vol_param.min, min(vol_param.max, float(volume)))
            vol_param.value = clamped
            return {
                "track_name": track.name,
                "volume": vol_param.value,
            }
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_panning(self, track_index, panning):
        """Set the mixer panning for a track.
        
        Args:
            track_index: 0-based track index
            panning: -1.0 (full left) to +1.0 (full right), 0.0 = center
        """
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            track = all_tracks[track_index]
            pan_param = track.mixer_device.panning
            clamped = max(pan_param.min, min(pan_param.max, float(panning)))
            pan_param.value = clamped
            return {
                "track_name": track.name,
                "panning": pan_param.value,
            }
        except Exception as e:
            self.log_message("Error setting track panning: " + str(e))
            raise

    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            api_used = self._write_notes(clip, notes)
            
            result = {
                "api": api_used,
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise

    # Browser helper methods

    def _normalize_browser_category_name(self, category_name):
        """Normalize browser category names for robust matching."""
        try:
            normalized = (category_name or "").strip().lower()
            normalized = normalized.replace("-", "_").replace(" ", "_")
            while "__" in normalized:
                normalized = normalized.replace("__", "_")
            normalized = normalized.strip("_")

            # Canonical category aliases
            alias_map = {
                "instrument": "instruments",
                "sound": "sounds",
                "drum": "drums",
                "audioeffects": "audio_effects",
                "audio_fx": "audio_effects",
                "audiofx": "audio_effects",
                "midieffects": "midi_effects",
                "midi_fx": "midi_effects",
                "midifx": "midi_effects",
                "plugin": "plugins",
                "vst": "plugins",
                "vst2": "plugins",
                "vst3": "plugins",
                "au": "plugins",
            }

            if normalized in alias_map:
                return alias_map[normalized]

            compact = normalized.replace("_", "")
            if compact in alias_map:
                return alias_map[compact]

            return normalized
        except Exception:
            return (category_name or "").strip().lower()

    def _split_browser_path(self, path):
        """Split a browser path into normalized path parts."""
        if not path:
            return []
        return [part.strip() for part in path.split("/") if part and part.strip()]

    def _resolve_browser_root_category(self, browser, root_category, browser_attrs=None):
        """Resolve a root browser category to the corresponding browser item."""
        normalized_root = self._normalize_browser_category_name(root_category)

        standard_roots = {
            "instruments": "instruments",
            "sounds": "sounds",
            "drums": "drums",
            "audio_effects": "audio_effects",
            "midi_effects": "midi_effects",
            "plugins": "plugins",
        }

        attr_name = standard_roots.get(normalized_root)
        if attr_name and hasattr(browser, attr_name):
            return getattr(browser, attr_name), attr_name

        attrs = browser_attrs if browser_attrs is not None else [a for a in dir(browser) if not a.startswith('_')]
        for attr in attrs:
            if self._normalize_browser_category_name(attr) == normalized_root:
                try:
                    return getattr(browser, attr), attr
                except Exception as e:
                    self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))

        return None, normalized_root
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = self._split_browser_path(path)
                if not path_parts:
                    result["error"] = "Invalid path"
                    return result
                
                # Determine the root based on the first part
                current_item, resolved_attr = self._resolve_browser_root_category(app.browser, path_parts[0])
                if current_item is None:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                elif resolved_attr != "instruments":
                    # Keep path parts aligned with resolved root
                    path_parts[0] = resolved_attr
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects,
                    browser_or_item.plugins,
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Arrangement command handlers

    def _get_arrangement_info(self, track_index):
        """Get arrangement clips and transport for one or all tracks."""
        try:
            transport = self._get_transport_info()
            tracks_data = []

            if track_index == -1:
                tracks = list(enumerate(self._song.tracks))
            else:
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                tracks = [(track_index, self._song.tracks[track_index])]

            for idx, track in tracks:
                is_group = bool(getattr(track, "is_foldable", False))
                if is_group and track_index == -1:
                    continue

                clips = []
                if not is_group:
                    for ci, clip in enumerate(track.arrangement_clips):
                        clip_info = self._get_arrangement_clip_info(clip)
                        clip_info["index"] = ci
                        clips.append(clip_info)

                tracks_data.append({
                    "index": idx,
                    "name": track.name,
                    "is_midi": track.has_midi_input,
                    "is_audio": track.has_audio_input,
                    "is_group_track": is_group,
                    "arrangement_clips": clips,
                    "clip_count": len(clips),
                })

            return {"transport": transport, "tracks": tracks_data}
        except Exception as e:
            self.log_message("Error getting arrangement info: " + str(e))
            raise

    def _get_cue_points(self):
        """Get all cue points."""
        try:
            cue_points = []
            for cp in self._song.cue_points:
                cue_points.append({"name": cp.name, "time": cp.time})
            return {"cue_points": cue_points}
        except Exception as e:
            self.log_message("Error getting cue points: " + str(e))
            raise

    def _set_song_time(self, time):
        """Set playback position."""
        try:
            self._song.current_song_time = time
            return {"time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error setting song time: " + str(e))
            raise

    def _set_arrangement_loop(self, enabled, start=None, length=None):
        """Set arrangement loop state and region."""
        try:
            self._song.loop = enabled
            if start is not None:
                self._song.loop_start = start
            if length is not None:
                self._song.loop_length = length
            return {
                "enabled": self._song.loop,
                "start": self._song.loop_start,
                "length": self._song.loop_length,
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _jump_to_cue(self, direction=None, name=None):
        """Jump to cue point by direction or name."""
        try:
            if direction == "next":
                self._song.jump_to_next_cue()
                return {"direction": "next", "time": self._song.current_song_time}
            elif direction == "prev":
                self._song.jump_to_prev_cue()
                return {"direction": "prev", "time": self._song.current_song_time}
            elif name:
                for cp in self._song.cue_points:
                    if cp.name == name:
                        cp.jump()
                        return {"name": cp.name, "time": cp.time}
                raise ValueError("Cue point '{0}' not found".format(name))
            else:
                raise ValueError("Provide direction ('next'/'prev') or name")
        except Exception as e:
            self.log_message("Error jumping to cue: " + str(e))
            raise

    def _create_cue_point(self, time, name=""):
        """Create a cue point at the given time."""
        try:
            for cp in tuple(self._song.cue_points):
                if abs(cp.time - time) < 0.01:
                    raise ValueError("Cue point already exists at this position: " + cp.name)
            self._song.current_song_time = time
            self._song.set_or_delete_cue()
            if name:
                for cp in tuple(self._song.cue_points):
                    if abs(cp.time - time) < 0.01:
                        cp.name = name
                        break
            return {"time": time, "name": name}
        except Exception as e:
            self.log_message("Error creating cue point: " + str(e))
            raise

    def _delete_cue_point(self, time):
        """Delete a cue point at the given time."""
        try:
            found = False
            for cp in self._song.cue_points:
                if abs(cp.time - time) < 0.01:
                    found = True
                    break
            if not found:
                raise ValueError("No cue point at this position")
            self._song.current_song_time = time
            self._song.set_or_delete_cue()
            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting cue point: " + str(e))
            raise

    def _validate_not_return_or_master(self, track_index):
        """Raise if track is a return or master track."""
        track = self._song.tracks[track_index]
        # Return tracks and master track are separate in the Live API,
        # but if accessed via tracks list they are regular tracks.
        # Check by comparing against return_tracks and master_track.
        for rt in self._song.return_tracks:
            if track == rt:
                raise ValueError("Cannot create arrangement clips on return track '{0}'".format(track.name))
        if track == self._song.master_track:
            raise ValueError("Cannot create arrangement clips on master track")

    def _create_arrangement_clip(self, track_index, position, length):
        """Create MIDI clip in arrangement."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._validate_not_return_or_master(track_index)
            track = self._song.tracks[track_index]
            overlapped = self._check_overlap(track, position, length)
            track.create_midi_clip(position, length)
            # Find the newly created clip
            result = {"start_time": position, "length": length, "is_midi": True}
            for clip in track.arrangement_clips:
                if abs(clip.start_time - position) < 0.01:
                    result = self._get_arrangement_clip_info(clip)
                    break
            result["overlapped_clips"] = overlapped
            return result
        except Exception as e:
            self.log_message("Error creating arrangement clip: " + str(e))
            raise

    def _create_arrangement_audio_clip(self, track_index, position, file_path):
        """Create audio clip in arrangement from file."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._validate_not_return_or_master(track_index)
            track = self._song.tracks[track_index]
            track.create_audio_clip(file_path, position)
            # Find the newly created clip
            result = {"start_time": position, "file_path": file_path, "is_audio": True}
            for clip in track.arrangement_clips:
                if abs(clip.start_time - position) < 0.01:
                    result = self._get_arrangement_clip_info(clip)
                    break
            return result
        except Exception as e:
            self.log_message("Error creating arrangement audio clip: " + str(e))
            raise

    def _duplicate_to_arrangement(self, track_index, clip_index, destination_time):
        """Duplicate a session clip to arrangement."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise ValueError("No clip in slot {0}".format(clip_index))
            clip = slot.clip
            track.duplicate_clip_to_arrangement(clip, destination_time)
            # Find the duplicated clip
            result = {"start_time": destination_time, "duplicated": True}
            for arr_clip in track.arrangement_clips:
                if abs(arr_clip.start_time - destination_time) < 0.01:
                    result = self._get_arrangement_clip_info(arr_clip)
                    result["duplicated"] = True
                    break
            return result
        except Exception as e:
            self.log_message("Error duplicating to arrangement: " + str(e))
            raise

    def _add_notes_to_arrangement_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to an arrangement clip."""
        try:
            track, clip = self._resolve_arrangement_clip(track_index, clip_index)
            if not clip.is_midi_clip:
                raise ValueError("Clip is not a MIDI clip")
            api_used = self._write_notes(clip, notes)
            return {"api": api_used, "note_count": len(notes)}
        except Exception as e:
            self.log_message("Error adding notes to arrangement clip: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, clip_index=None, clip_name=None):
        """Delete an arrangement clip."""
        try:
            track, clip = self._resolve_arrangement_clip(track_index, clip_index, clip_name)
            track.delete_clip(clip)
            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise

    def _set_arrangement_clip_property(self, track_index, clip_index, property_name, value):
        """Set a property on an arrangement clip."""
        try:
            ALLOWED = ("name", "muted", "color", "looping", "loop_start", "loop_end",
                       "gain", "pitch_coarse", "pitch_fine", "warping", "warp_mode")
            if property_name not in ALLOWED:
                raise ValueError("Property '{0}' not allowed. Allowed: {1}".format(
                    property_name, ", ".join(ALLOWED)))
            track, clip = self._resolve_arrangement_clip(track_index, clip_index)
            setattr(clip, property_name, value)
            return {"property": property_name, "value": getattr(clip, property_name)}
        except Exception as e:
            self.log_message("Error setting arrangement clip property: " + str(e))
            raise

    def _set_view(self, view_name):
        """Switch Ableton view."""
        try:
            app = self.application()
            app.view.show_view(view_name)
            return {"visible": app.view.is_view_visible(view_name)}
        except Exception as e:
            self.log_message("Error setting view: " + str(e))
            raise

    def _control_arrangement_view(self, action, track_index=0):
        """Dispatch arrangement view control actions."""
        try:
            app = self.application()
            if action == "zoom_in":
                app.view.zoom_view(1, "Arranger", False)
            elif action == "zoom_out":
                app.view.zoom_view(0, "Arranger", False)
            elif action == "scroll_right":
                app.view.scroll_view(1, "Arranger", False)
            elif action == "scroll_left":
                app.view.scroll_view(0, "Arranger", False)
            elif action == "follow_on":
                self._song.view.follow_song = True
            elif action == "follow_off":
                self._song.view.follow_song = False
            elif action == "collapse_track":
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                self._song.tracks[track_index].view.is_collapsed = True
            elif action == "expand_track":
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                self._song.tracks[track_index].view.is_collapsed = False
            else:
                raise ValueError("Unknown action: " + action)
            return {"action": action, "done": True}
        except Exception as e:
            self.log_message("Error controlling arrangement view: " + str(e))
            raise

    def _manage_clip_automation(self, track_index, clip_index, action, parameter_name=""):
        """Create or clear automation envelopes."""
        try:
            track, clip = self._resolve_arrangement_clip(track_index, clip_index)
            if action == "clear_all":
                clip.clear_all_envelopes()
                return {"action": "clear_all", "done": True}
            # Find the parameter
            param = None
            # Check mixer device first
            mixer = track.mixer_device
            for p in [mixer.volume, mixer.panning]:
                if p.name.lower() == parameter_name.lower():
                    param = p
                    break
            # Check sends
            if param is None:
                for send in mixer.sends:
                    if send.name.lower() == parameter_name.lower():
                        param = send
                        break
            # Check track devices
            if param is None:
                for device in track.devices:
                    for p in device.parameters:
                        if p.name.lower() == parameter_name.lower():
                            param = p
                            break
                    if param:
                        break
            if param is None:
                raise ValueError("Parameter '{0}' not found on track '{1}'".format(
                    parameter_name, track.name))
            if action == "create":
                clip.create_automation_envelope(param)
                return {"action": "create", "parameter": param.name, "done": True}
            elif action == "clear":
                clip.clear_envelope(param)
                return {"action": "clear", "parameter": param.name, "done": True}
            else:
                raise ValueError("Unknown action: " + action)
        except Exception as e:
            self.log_message("Error managing clip automation: " + str(e))
            raise

    # ── Device command handlers ──────────────────────────────────────

    def _get_device_parameters(self, track_index, device_index, chain_index=None, show_all=False):
        """Return parameter list for a device."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            # If chain_index, navigate into chain
            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chains = device.chains
                if chain_index < 0 or chain_index >= len(chains):
                    raise IndexError("Chain index {0} out of range".format(chain_index))
                chain = chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain '{0}' has no devices".format(chain.name))
                target_device = chain.devices[0]

            params = target_device.parameters
            param_list = []
            for i, p in enumerate(params):
                pmin = p.min
                pmax = p.max
                raw_val = p.value
                norm = (raw_val - pmin) / (pmax - pmin) if pmax != pmin else 0.0
                entry = {
                    "index": i,
                    "name": p.name,
                    "value": round(norm, 4),
                    "min": pmin,
                    "max": pmax,
                    "display_value": str(p),
                    "is_enabled": p.is_enabled,
                    "is_quantized": p.is_quantized,
                    "value_items": list(p.value_items) if p.is_quantized else [],
                }
                param_list.append(entry)

            result = {
                "device_name": target_device.name,
                "device_class": target_device.class_name,
                "parameter_count": len(params),
                "parameters": param_list,
            }
            return result
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, chain_index=None,
                              parameter_name=None, parameter_index=None, value=0.0):
        """Set a device parameter by name or index. Value is normalized 0.0-1.0."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain '{0}' has no devices".format(chain.name))
                target_device = chain.devices[0]

            param, match_type = self._find_parameter(
                target_device, name=parameter_name, index=parameter_index)

            if not param.is_enabled:
                raise ValueError("Parameter '{0}' is currently disabled".format(param.name))

            pmin = param.min
            pmax = param.max
            old_norm = (param.value - pmin) / (pmax - pmin) if pmax != pmin else 0.0

            # Clamp normalized value
            clamped = max(0.0, min(1.0, value))
            was_clamped = (clamped != value)

            # Denormalize
            raw_value = pmin + clamped * (pmax - pmin)
            param.value = raw_value

            return {
                "parameter_name": param.name,
                "old_value": round(old_norm, 4),
                "new_value": round(clamped, 4),
                "display_value": str(param),
                "clamped": was_clamped,
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _set_device_enabled(self, track_index, device_index, chain_index=None, enabled=True):
        """Enable or disable a device via its 'Device On' parameter."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain has no devices")
                target_device = chain.devices[0]

            # Use "Device On" parameter (always index 0) instead of
            # is_active which is read-only in the Live API.
            params = target_device.parameters
            if not params:
                raise ValueError("Device '{0}' has no parameters".format(target_device.name))
            on_param = params[0]
            on_param.value = on_param.max if enabled else on_param.min

            return {
                "device_name": target_device.name,
                "is_active": enabled,
            }
        except Exception as e:
            self.log_message("Error setting device enabled: " + str(e))
            raise

    def _get_chain_info(self, track_index, device_index, chain_index=None):
        """Get chain information for a rack device."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            if not device.can_have_chains:
                raise ValueError("Device '{0}' is not a rack and has no chains".format(device.name))

            if chain_index is not None:
                # Detail for a specific chain
                chains = device.chains
                if chain_index < 0 or chain_index >= len(chains):
                    raise IndexError("Chain index {0} out of range".format(chain_index))
                chain = chains[chain_index]
                devices = []
                for di, d in enumerate(chain.devices):
                    devices.append({
                        "index": di,
                        "name": d.name,
                        "class_name": d.class_name,
                        "type": self._get_device_type(d),
                        "is_active": d.is_active,
                        "parameter_count": len(d.parameters),
                    })
                return {
                    "chain_name": chain.name,
                    "devices": devices,
                }
            else:
                # List all chains
                chain_list = []
                for ci, chain in enumerate(device.chains):
                    chain_devices = []
                    for di, d in enumerate(chain.devices):
                        chain_devices.append({
                            "index": di,
                            "name": d.name,
                            "type": self._get_device_type(d),
                        })
                    chain_list.append({
                        "index": ci,
                        "name": chain.name,
                        "mute": chain.mute,
                        "solo": chain.solo,
                        "device_count": len(chain.devices),
                        "devices": chain_devices,
                    })
                return {
                    "device_name": device.name,
                    "chain_count": len(device.chains),
                    "chains": chain_list,
                }
        except Exception as e:
            self.log_message("Error getting chain info: " + str(e))
            raise

    def _get_drum_pad_info(self, track_index, device_index):
        """Get drum pad info for a Drum Rack."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            if not device.can_have_drum_pads:
                raise ValueError("Device '{0}' is not a Drum Rack".format(device.name))

            filled_pads = []
            for pad in device.drum_pads:
                if pad.chains:
                    pad_devices = []
                    for chain in pad.chains:
                        for d in chain.devices:
                            pad_devices.append({
                                "index": 0,
                                "name": d.name,
                                "type": self._get_device_type(d),
                            })
                    filled_pads.append({
                        "note": pad.note,
                        "name": pad.name,
                        "mute": pad.mute,
                        "solo": pad.solo,
                        "chains": [{
                            "name": c.name,
                            "devices": [{"index": di, "name": d.name, "type": self._get_device_type(d)}
                                        for di, d in enumerate(c.devices)]
                        } for c in pad.chains],
                    })

            return {
                "device_name": device.name,
                "filled_pads": filled_pads,
            }
        except Exception as e:
            self.log_message("Error getting drum pad info: " + str(e))
            raise

    def _delete_device(self, track_index, device_index):
        """Delete a device from a track."""
        try:
            track, device = self._resolve_device(track_index, device_index)
            device_name = device.name
            track.delete_device(device_index)
            return {
                "deleted_device": device_name,
                "remaining_devices": len(track.devices),
            }
        except Exception as e:
            self.log_message("Error deleting device: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a track from the session."""
        try:
            if len(self._song.tracks) <= 1:
                raise ValueError(
                    "Cannot delete the last remaining session track. "
                    "Ableton must always have at least one track."
                )
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(self._song.tracks) - 1))
            track_name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)
            return {
                "deleted_track": track_name,
                "remaining_tracks": len(self._song.tracks),
            }
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _navigate_preset(self, track_index, device_index, chain_index=None, direction="current"):
        """Navigate device presets."""
        try:
            track, device = self._resolve_device(track_index, device_index)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain has no devices")
                target_device = chain.devices[0]

            if not hasattr(target_device, 'presets') or not target_device.presets:
                raise ValueError("Device '{0}' has no presets available".format(
                    target_device.name))

            presets = list(target_device.presets)
            current_idx = target_device.selected_preset_index

            if direction == "next":
                new_idx = min(current_idx + 1, len(presets) - 1)
                target_device.selected_preset_index = new_idx
            elif direction == "previous":
                new_idx = max(current_idx - 1, 0)
                target_device.selected_preset_index = new_idx
            elif direction == "current":
                new_idx = current_idx
            else:
                raise ValueError("Invalid direction: {0}".format(direction))

            return {
                "device_name": target_device.name,
                "preset_name": presets[new_idx] if new_idx < len(presets) else "",
                "preset_index": new_idx,
                "preset_count": len(presets),
            }
        except Exception as e:
            self.log_message("Error navigating preset: " + str(e))
            raise

    # Device helper methods

    def _resolve_device(self, track_index, device_index, chain_index=None):
        """Resolve a device reference to (track, device) tuple.

        Parameters:
        - track_index: 0-based track index
        - device_index: 0-based device index on track (or within chain)
        - chain_index: optional 0-based chain index for rack devices

        Returns (track, device) tuple.
        Raises IndexError or ValueError on invalid references.
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))

        track = self._song.tracks[track_index]

        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index {0} out of range on track '{1}' (0-{2})".format(
                device_index, track.name,
                len(track.devices) - 1 if track.devices else 0))

        device = track.devices[device_index]

        if chain_index is not None:
            # Navigate into rack chain
            if not device.can_have_chains:
                raise ValueError("Device '{0}' is not a rack and has no chains".format(device.name))
            chains = device.chains
            if chain_index < 0 or chain_index >= len(chains):
                raise IndexError("Chain index {0} out of range on '{1}' (0-{2})".format(
                    chain_index, device.name, len(chains) - 1))
            # Return the first device in the chain (or the chain's device list)
            # For now, return the chain's first device. If a nested device_index
            # is needed, callers can extend this.
            chain = chains[chain_index]
            if not chain.devices:
                raise ValueError("Chain '{0}' has no devices".format(chain.name))
            # Use device_index 0 within the chain for now (callers pass separate index)
            return track, device

        return track, device

    def _find_parameter(self, device, name=None, index=None):
        """Find a parameter on a device by name or index.

        Lookup order:
        1. Exact name match (case-sensitive)
        2. Case-insensitive exact match
        3. Case-insensitive partial match
        4. By 0-based index

        Returns (parameter, match_type) tuple where match_type is
        'exact', 'case_insensitive', 'partial', or 'index'.
        Raises ValueError if not found.
        """
        params = device.parameters

        if name is not None:
            # Step 1: exact match
            for p in params:
                if p.name == name:
                    return p, "exact"

            # Step 2: case-insensitive exact match
            name_lower = name.lower()
            for p in params:
                if p.name.lower() == name_lower:
                    return p, "case_insensitive"

            # Step 3: case-insensitive partial match
            for p in params:
                if name_lower in p.name.lower():
                    return p, "partial"

            raise ValueError("Parameter '{0}' not found on device '{1}'".format(
                name, device.name))

        if index is not None:
            if index < 0 or index >= len(params):
                raise IndexError("Parameter index {0} out of range on '{1}' (0-{2})".format(
                    index, device.name, len(params) - 1))
            return params[index], "index"

        raise ValueError("Either name or index must be provided")

    def _get_device_info(self, device):
        """Build a device info dict."""
        info = {
            "name": device.name,
            "class_name": device.class_name,
            "type": self._get_device_type(device),
            "is_active": device.is_active,
            "can_have_chains": device.can_have_chains,
            "can_have_drum_pads": device.can_have_drum_pads,
            "parameter_count": len(device.parameters),
        }
        try:
            info["class_display_name"] = device.class_display_name
        except Exception:
            info["class_display_name"] = device.class_name
        return info

    # General helper methods

    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = self._split_browser_path(path)
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0]
            current_item, resolved_root = self._resolve_browser_root_category(
                app.browser, root_category, browser_attrs
            )
            if current_item is None:
                # If we still haven't found the category, return available categories
                return {
                    "path": path,
                    "error": "Unknown or unavailable category: {0}".format(
                        self._normalize_browser_category_name(root_category)
                    ),
                    "available_categories": browser_attrs,
                    "items": []
                }

            # Keep path canonicalized to resolved root category
            path_parts[0] = resolved_root
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _get_clip_notes(self, track_index, clip_index):
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise Exception("No clip in slot")
            clip = slot.clip
            if not getattr(clip, "is_midi_clip", False):
                raise Exception("Clip is not a MIDI clip")
            notes = self._notes_from_clip(clip)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip.name,
                "length": float(clip.length),
                "note_count": len(notes),
                "notes": notes,
            }
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _clear_notes_from_clip(self, track_index, clip_index):
        """Remove all MIDI notes from a Session clip.

        Pairs with _add_notes_to_clip to make a real replace (clear, then add),
        which the write-only API otherwise can't do. Counts notes first so the
        result can report how many were removed.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip; no notes to clear")

            length = clip.length

            # Count existing notes for the report (best-effort; never fatal).
            cleared = 0
            try:
                getter = getattr(clip, "get_notes_extended", None)
                if getter is not None:
                    cleared = len(list(getter(0, 128, 0.0, length)))
                else:
                    cleared = len(list(clip.get_notes(0.0, 0, length, 128)))
            except Exception:
                cleared = 0

            # Remove every note across the full pitch/time range. Prefer the
            # modern API (Live 11+); fall back to the legacy signature. Argument
            # order mirrors the get/remove _extended family:
            #   remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
            # vs the legacy remove_notes(from_time, from_pitch, time_span, pitch_span).
            remover = getattr(clip, "remove_notes_extended", None)
            if remover is not None:
                remover(0, 128, 0.0, length)
            else:
                clip.remove_notes(0.0, 0, length, 128)

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip.name,
                "cleared_count": cleared,
            }
        except Exception as e:
            self.log_message("Error clearing notes from clip: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete the clip in the given clip slot, freeing the slot for reuse."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                return {"deleted": False, "reason": "Clip slot was already empty"}

            clip_slot.delete_clip()

            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            # Create the track
            self._song.create_audio_track(index)

            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    def _get_session_snapshot(self, include_notes=True, include_params=True):
        """Full v2 project state dump for trajectory dataset recording."""
        try:
            session = self._get_session_info()
            tracks = []
            for track_index, track in enumerate(self._song.tracks):
                clip_slots = []
                for slot_index, slot in enumerate(track.clip_slots):
                    clip_info = None
                    if slot.has_clip:
                        clip_info = self._serialize_session_clip(
                            slot.clip, include_notes=include_notes
                        )
                    clip_slots.append({
                        "index": slot_index,
                        "has_clip": bool(slot.has_clip),
                        "clip": clip_info,
                    })

                devices = []
                for device_index, device in enumerate(track.devices):
                    devices.append(
                        self._serialize_device(
                            device, device_index, include_params=include_params
                        )
                    )

                arrangement_clips = []
                try:
                    for clip in track.arrangement_clips:
                        arrangement_clips.append(
                            self._serialize_arrangement_clip(
                                clip, include_notes=include_notes
                            )
                        )
                except Exception as e:
                    self.log_message(
                        "arrangement_clips unavailable on track %d: %s"
                        % (track_index, str(e))
                    )

                tracks.append({
                    "index": track_index,
                    "name": track.name,
                    "is_audio_track": bool(track.has_audio_input),
                    "is_midi_track": bool(track.has_midi_input),
                    "mute": bool(track.mute),
                    "solo": bool(track.solo),
                    "arm": bool(getattr(track, "arm", False)),
                    "volume": float(track.mixer_device.volume.value),
                    "panning": float(track.mixer_device.panning.value),
                    "sends": self._safe_sends(track),
                    "clip_slots": clip_slots,
                    "devices": devices,
                    "arrangement_clips": arrangement_clips,
                })

            return {
                "schema": "ableton_mcp_snapshot_v2",
                "session": session,
                "tracks": tracks,
                "scenes": self._serialize_scenes(),
                "return_tracks": self._serialize_return_tracks(
                    include_params=include_params
                ),
                "master_track": self._serialize_master_track(
                    include_params=include_params
                ),
                "cue_points": self._serialize_cue_points(),
                "include_notes": bool(include_notes),
                "include_params": bool(include_params),
            }
        except Exception as e:
            self.log_message("Error getting session snapshot: " + str(e))
            raise

    def _notes_from_clip(self, clip):
        """Extract MIDI notes from a clip (incl. MPE/expression when available)."""
        notes = []
        if not clip or not getattr(clip, "is_midi_clip", False):
            return notes

        if hasattr(clip, "get_notes_extended"):
            try:
                raw = clip.get_notes_extended(0, 128, 0.0, float(clip.length) + 1.0)
                for n in raw:
                    entry = {
                        "pitch": int(getattr(n, "pitch", 0)),
                        "start_time": float(getattr(n, "start_time", 0.0)),
                        "duration": float(getattr(n, "duration", 0.0)),
                        "velocity": float(getattr(n, "velocity", 0)),
                        "mute": bool(getattr(n, "mute", False)),
                    }
                    for opt, caster in [
                        ("probability", float),
                        ("velocity_deviation", float),
                        ("release_velocity", float),
                        ("note_id", int),
                    ]:
                        if hasattr(n, opt):
                            try:
                                entry[opt] = caster(getattr(n, opt))
                            except Exception:
                                pass
                    for opt in ("pitch_bend_range", "pressure", "timbre", "slide"):
                        if hasattr(n, opt):
                            try:
                                entry[opt] = float(getattr(n, opt))
                            except Exception:
                                pass
                    notes.append(entry)
                return notes
            except Exception as e:
                self.log_message("get_notes_extended failed, falling back: " + str(e))

        if hasattr(clip, "get_notes"):
            try:
                raw = clip.get_notes(0.0, 0, float(clip.length) + 1.0, 128)
                for n in raw:
                    notes.append({
                        "pitch": int(n[0]),
                        "start_time": float(n[1]),
                        "duration": float(n[2]),
                        "velocity": float(n[3]),
                        "mute": bool(n[4]) if len(n) > 4 else False,
                    })
            except Exception as e:
                self.log_message("get_notes failed: " + str(e))
        return notes

    def _serialize_arrangement_clip(self, clip, include_notes=True):
        info = {
            "name": clip.name,
            "start_time": float(clip.start_time),
            "end_time": float(clip.end_time),
            "length": float(clip.length),
            "color": int(getattr(clip, "color", 0)),
            "is_midi_clip": bool(getattr(clip, "is_midi_clip", False)),
            "is_audio_clip": bool(getattr(clip, "is_audio_clip", False)),
            "is_playing": bool(getattr(clip, "is_playing", False)),
        }
        info.update(self._serialize_clip_common(clip))
        if include_notes and info["is_midi_clip"]:
            info["notes"] = self._notes_from_clip(clip)
            info["note_count"] = len(info["notes"])
        return info

    def _serialize_cue_points(self):
        cues = []
        try:
            for cue in self._song.cue_points:
                cues.append({
                    "name": str(getattr(cue, "name", "")),
                    "time": float(getattr(cue, "time", 0.0)),
                })
        except Exception as e:
            self.log_message("cue_points serialize failed: " + str(e))
        return cues

    def _serialize_device(self, device, device_index, include_params=True, depth=0):
        info = {
            "index": device_index,
            "name": device.name,
            "class_name": device.class_name,
            "type": self._get_device_type(device),
        }
        automated = self._automated_params_for_device(device)
        if automated:
            info["automated_parameters"] = automated
            info["automation_enabled"] = True
        else:
            info["automation_enabled"] = False

        if include_params:
            params = []
            try:
                for p_index, param in enumerate(device.parameters):
                    try:
                        entry = {
                            "index": p_index,
                            "name": param.name,
                            "value": float(param.value),
                            "min": float(param.min),
                            "max": float(param.max),
                            "is_enabled": bool(getattr(param, "is_enabled", True)),
                            "is_quantized": bool(getattr(param, "is_quantized", False)),
                        }
                        if hasattr(param, "value_string"):
                            entry["value_string"] = str(param.value_string)
                        if hasattr(param, "automation_state"):
                            try:
                                entry["automation_state"] = int(param.automation_state)
                            except Exception:
                                pass
                        params.append(entry)
                    except Exception:
                        continue
            except Exception as e:
                self.log_message("Error reading device parameters: " + str(e))
            info["parameters"] = params

        # Devices inside a rack carry the actual sound design — a drum rack's
        # nested Operator, an instrument rack's filter. Without this walk a rack
        # contributes only its 8 macros and the timbral state is invisible.
        if getattr(device, "can_have_chains", False):
            if depth >= self._MAX_CHAIN_DEPTH:
                info["chains_truncated"] = True
            else:
                info["chains"] = self._serialize_chains(
                    device, include_params=include_params, depth=depth
                )
        return info

    def _serialize_master_track(self, include_params=True):
        """Master chain — the bus compressor/limiter that shapes the final sound."""
        try:
            track = self._song.master_track
            devices = []
            for d_i, device in enumerate(track.devices):
                devices.append(
                    self._serialize_device(device, d_i, include_params=include_params)
                )
            return {
                "volume": float(track.mixer_device.volume.value),
                "panning": float(track.mixer_device.panning.value),
                "devices": devices,
            }
        except Exception as e:
            self.log_message("master_track serialize failed: " + str(e))
            return None

    def _serialize_return_tracks(self, include_params=True):
        returns = []
        try:
            for i, track in enumerate(self._song.return_tracks):
                devices = []
                for d_i, device in enumerate(track.devices):
                    devices.append(
                        self._serialize_device(device, d_i, include_params=include_params)
                    )
                returns.append({
                    "index": i,
                    "name": track.name,
                    "mute": bool(track.mute),
                    "solo": bool(track.solo),
                    "volume": float(track.mixer_device.volume.value),
                    "panning": float(track.mixer_device.panning.value),
                    "devices": devices,
                })
        except Exception as e:
            self.log_message("return_tracks serialize failed: " + str(e))
        return returns

    def _serialize_scenes(self):
        scenes = []
        try:
            for i, scene in enumerate(self._song.scenes):
                scenes.append({
                    "index": i,
                    "name": str(scene.name),
                    "tempo": self._safe_attr(scene, "tempo", float, None),
                    "is_triggered": bool(self._safe_attr(scene, "is_triggered", bool, False)),
                })
        except Exception as e:
            self.log_message("scenes serialize failed: " + str(e))
        return scenes

    def _serialize_sends(self, track):
        sends = []
        try:
            for i, send in enumerate(track.mixer_device.sends):
                sends.append({
                    "index": i,
                    "value": float(send.value),
                    "name": str(getattr(send, "name", "Send %d" % i)),
                })
        except Exception:
            pass
        return sends

    def _serialize_session_clip(self, clip, include_notes=True):
        info = {
            "name": clip.name,
            "length": float(clip.length),
            "is_playing": bool(clip.is_playing),
            "is_recording": bool(getattr(clip, "is_recording", False)),
            "is_midi_clip": bool(getattr(clip, "is_midi_clip", False)),
            "is_audio_clip": bool(getattr(clip, "is_audio_clip", False)),
            "color": int(getattr(clip, "color", 0)),
        }
        info.update(self._serialize_clip_common(clip))
        if include_notes and info["is_midi_clip"]:
            info["notes"] = self._notes_from_clip(clip)
            info["note_count"] = len(info["notes"])
        return info

    def _serialize_clip_common(self, clip):
        info = {
            "looping": bool(self._safe_attr(clip, "looping", bool, False)),
            "loop_start": self._safe_attr(clip, "loop_start", float, None),
            "loop_end": self._safe_attr(clip, "loop_end", float, None),
            "warping": bool(self._safe_attr(clip, "warping", bool, False)),
            "warp_mode": self._safe_attr(clip, "warp_mode", int, None),
            "gain": self._safe_attr(clip, "gain", float, None),
            "pitch_coarse": self._safe_attr(clip, "pitch_coarse", int, None),
            "pitch_fine": self._safe_attr(clip, "pitch_fine", int, None),
            "launch_mode": self._safe_attr(clip, "launch_mode", int, None),
        }
        for attr in ("file_path", "file_path_relative"):
            path = self._safe_attr(clip, attr, str, None)
            if path:
                info["file_path"] = path
                break
        markers = self._warp_markers_from_clip(clip)
        if markers:
            info["warp_markers"] = markers
            info["warp_marker_count"] = len(markers)
        return dict((k, v) for k, v in info.items() if v is not None)

    def _automated_params_for_device(self, device):
        automated = []
        try:
            for param in device.parameters:
                is_auto = False
                try:
                    if hasattr(param, "automation_state"):
                        is_auto = int(param.automation_state) != 0
                    elif hasattr(param, "is_automated"):
                        is_auto = bool(param.is_automated)
                except Exception:
                    continue
                if is_auto:
                    automated.append(param.name)
        except Exception:
            pass
        return automated

    # Racks nest, and a pathological project could nest deeply. Cap the walk so
    # a snapshot can never blow the stack or the payload size.
    _MAX_CHAIN_DEPTH = 4

    def _serialize_chains(self, rack, include_params=True, depth=0):
        chains = []
        try:
            chain_lists = [("chains", getattr(rack, "chains", []))]
            returns = getattr(rack, "return_chains", None)
            if returns:
                chain_lists.append(("return_chains", returns))

            for kind, chain_list in chain_lists:
                for chain_index, chain in enumerate(chain_list):
                    entry = {
                        "index": chain_index,
                        "kind": kind,
                        "chain_name": self._safe_attr(chain, "name", str, ""),
                        "mute": bool(self._safe_attr(chain, "mute", bool, False)),
                        "solo": bool(self._safe_attr(chain, "solo", bool, False)),
                    }
                    try:
                        mixer = chain.mixer_device
                        entry["volume"] = float(mixer.volume.value)
                        entry["panning"] = float(mixer.panning.value)
                    except Exception:
                        pass

                    # Drum racks expose the pad's note, which is what ties a
                    # nested device back to the kick/snare/hat it voices.
                    note = self._safe_attr(chain, "out_note", int, None)
                    if note is not None:
                        entry["out_note"] = note

                    nested = []
                    try:
                        for d_i, dev in enumerate(chain.devices):
                            nested.append(
                                self._serialize_device(
                                    dev,
                                    d_i,
                                    include_params=include_params,
                                    depth=depth + 1,
                                )
                            )
                    except Exception as e:
                        self.log_message("Error reading chain devices: " + str(e))
                    entry["devices"] = nested
                    chains.append(entry)
        except Exception as e:
            self.log_message("Error serializing rack chains: " + str(e))
        return chains

    def _safe_attr(self, obj, attr, cast=None, default=None):
        try:
            val = getattr(obj, attr)
            if callable(val):
                return default
            if cast is not None:
                return cast(val)
            return val
        except Exception:
            return default

    def _warp_markers_from_clip(self, clip):
        markers = []
        try:
            raw = getattr(clip, "warp_markers", None)
            if not raw:
                return markers
            for m in raw:
                markers.append({
                    "beat_time": float(getattr(m, "beat_time", getattr(m, "time", 0.0))),
                    "sample_time": float(
                        getattr(m, "sample_time", getattr(m, "time", 0.0))
                    ),
                })
        except Exception as e:
            self.log_message("warp_markers read failed: " + str(e))
        return markers

    def _set_track_state(self, track_index, mute=None, solo=None, arm=None):
        """Toggle mute / solo / arm on a track. Only supplied flags are changed.

        Live exposes these as plain booleans on the track; the fork previously
        read them in _get_track_info but offered no way to set them.
        """
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            track = all_tracks[track_index]
            changed = {}
            if mute is not None:
                track.mute = bool(mute)
                changed["mute"] = bool(track.mute)
            if solo is not None:
                track.solo = bool(solo)
                changed["solo"] = bool(track.solo)
            if arm is not None:
                if not hasattr(track, "arm") or getattr(track, "is_foldable", False):
                    raise Exception("Track cannot be armed (group or return track)")
                track.arm = bool(arm)
                changed["arm"] = bool(track.arm)
            return {"track_name": track.name, "changed": changed}
        except Exception as e:
            self.log_message("Error setting track state: " + str(e))
            raise

    def _set_send_level(self, track_index, send_index, value):
        """Set one send level (normalized 0.0-1.0) from a track to a return."""
        try:
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            track = all_tracks[track_index]
            sends = track.mixer_device.sends
            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index {0} out of range (0-{1})".format(
                    send_index, len(sends) - 1))
            param = sends[send_index]
            param.value = max(param.min, min(param.max, float(value)))
            return {
                "track_name": track.name,
                "send_index": send_index,
                "send_name": param.name,
                "value": param.value,
            }
        except Exception as e:
            self.log_message("Error setting send level: " + str(e))
            raise

    def _safe_sends(self, track):
        """_serialize_sends, but never fatal for tracks that have no sends."""
        try:
            return self._serialize_sends(track)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Specialised device support (Wavetable modulation matrix)
    #
    # Wavetable is a WavetableDevice, not a plain Device: the matrix, the
    # wavetable selectors and the voicing controls live on the object itself
    # and never appear in device.parameters. The Live 11 API docs list only
    # get_modulation_value with no setter, so _describe_device_api exists to
    # find out what this build of Live actually offers.
    # ------------------------------------------------------------------

    def _resolve_device_in_chain(self, track_index, device_index, chain_index=None):
        """Resolve a device, descending into a rack chain when asked."""
        track, device = self._resolve_device(track_index, device_index)
        if chain_index is not None and chain_index >= 0:
            if not getattr(device, "can_have_chains", False):
                raise ValueError("Device '{0}' is not a rack".format(device.name))
            chains = list(device.chains)
            if chain_index >= len(chains):
                raise IndexError("Chain index {0} out of range (0-{1})".format(
                    chain_index, len(chains) - 1))
            chain = chains[chain_index]
            if not chain.devices:
                raise ValueError("Chain '{0}' has no devices".format(chain.name))
            device = chain.devices[0]
        return track, device

    def _describe_device_api(self, track_index, device_index, chain_index=None):
        """Report what the live object actually exposes.

        Docs describe the API in general; this reports the truth for the build
        of Live currently running, which is what the matrix work depends on.
        """
        try:
            track, device = self._resolve_device_in_chain(
                track_index, device_index, chain_index)
            members = [m for m in dir(device) if not m.startswith("__")]
            methods, props = [], []
            for m in members:
                try:
                    attr = getattr(device, m)
                except Exception as e:
                    props.append({"name": m, "error": str(e)[:80]})
                    continue
                if callable(attr):
                    doc = (getattr(attr, "__doc__", "") or "").strip()
                    methods.append({"name": m, "doc": doc[:200]})
                else:
                    props.append({"name": m, "type": type(attr).__name__})
            return {
                "device_name": device.name,
                "class_name": device.class_name,
                "method_count": len(methods),
                "property_count": len(props),
                "methods": methods,
                "properties": props,
                "modulation_api": {
                    n: hasattr(device, n) for n in (
                        "get_modulation_value", "set_modulation_value",
                        "get_modulation_target_parameter_name",
                        "add_parameter_to_modulation_matrix",
                        "is_parameter_modulatable",
                        "visible_modulation_target_names")
                },
            }
        except Exception as e:
            self.log_message("Error describing device api: " + str(e))
            raise

    def _wavetable_source_map(self):
        """ModulationSource enum name -> int, read from the live enum itself.

        ModulationSource is a class inside the Live.WavetableDevice module, so
        the path is module.class. The nested form is tried as well in case a
        future version moves it onto the device class.
        """
        enum = None
        try:
            import Live
            for path in (("WavetableDevice", "ModulationSource"),
                         ("WavetableDevice", "WavetableDevice", "ModulationSource")):
                obj = Live
                ok = True
                for part in path:
                    try:
                        obj = getattr(obj, part)
                    except AttributeError:
                        ok = False
                        break
                if ok:
                    enum = obj
                    break
        except Exception as e:
            self.log_message("ModulationSource lookup failed: " + str(e))
            return {}
        if enum is None:
            self.log_message("ModulationSource enum not found on Live module")
            return {}
        out = {}
        for name in dir(enum):
            if name.startswith("_"):
                continue
            try:
                out[name] = int(getattr(enum, name))
            except Exception:
                pass
        return out

    def _get_wavetable_state(self, track_index, device_index, chain_index=None):
        """Full Wavetable state: matrix, wavetables, voicing, routing."""
        try:
            track, device = self._resolve_device_in_chain(
                track_index, device_index, chain_index)
            if not hasattr(device, "visible_modulation_target_names"):
                raise ValueError(
                    "Device '{0}' ({1}) is not a Wavetable".format(
                        device.name, device.class_name))

            targets = list(device.visible_modulation_target_names)
            sources = self._wavetable_source_map()

            matrix = []
            for ti in range(len(targets)):
                try:
                    tname = device.get_modulation_target_parameter_name(ti)
                except Exception:
                    tname = targets[ti] if ti < len(targets) else str(ti)
                row = {"target_index": ti, "target": tname, "amounts": {}}
                for sname, sval in sorted(sources.items()):
                    try:
                        amt = float(device.get_modulation_value(ti, sval))
                    except Exception:
                        continue
                    if amt:
                        row["amounts"][sname] = amt
                matrix.append(row)

            def safe(name):
                try:
                    v = getattr(device, name)
                    return list(v) if hasattr(v, "__iter__") and not isinstance(v, str) else v
                except Exception:
                    return None

            return {
                "device_name": device.name,
                "class_name": device.class_name,
                "modulation_sources": sources,
                "visible_targets": targets,
                "matrix": matrix,
                "can_set_modulation": hasattr(device, "set_modulation_value"),
                "wavetable_categories": safe("oscillator_wavetable_categories"),
                "osc1": {
                    "category": safe("oscillator_1_wavetable_category"),
                    "index": safe("oscillator_1_wavetable_index"),
                    "effect_mode": safe("oscillator_1_effect_mode"),
                    "wavetables": safe("oscillator_1_wavetables"),
                },
                "osc2": {
                    "category": safe("oscillator_2_wavetable_category"),
                    "index": safe("oscillator_2_wavetable_index"),
                    "effect_mode": safe("oscillator_2_effect_mode"),
                    "wavetables": safe("oscillator_2_wavetables"),
                },
                "filter_routing": safe("filter_routing"),
                "mono_poly": safe("mono_poly"),
                "poly_voices": safe("poly_voices"),
                "unison_mode": safe("unison_mode"),
                "unison_voice_count": safe("unison_voice_count"),
            }
        except Exception as e:
            self.log_message("Error getting wavetable state: " + str(e))
            raise

    WAVETABLE_WRITABLE = (
        "oscillator_1_wavetable_category", "oscillator_1_wavetable_index",
        "oscillator_2_wavetable_category", "oscillator_2_wavetable_index",
        "oscillator_1_effect_mode", "oscillator_2_effect_mode",
        "filter_routing", "mono_poly", "poly_voices",
        "unison_mode", "unison_voice_count",
    )

    def _set_wavetable_property(self, track_index, device_index, chain_index,
                                name, value):
        """Set one of Wavetable's own (non-parameter) properties."""
        try:
            if name not in self.WAVETABLE_WRITABLE:
                raise ValueError("Property '{0}' not writable. Allowed: {1}".format(
                    name, ", ".join(self.WAVETABLE_WRITABLE)))
            track, device = self._resolve_device_in_chain(
                track_index, device_index, chain_index)
            setattr(device, name, int(value))
            return {"device_name": device.name, "property": name,
                    "value": getattr(device, name)}
        except Exception as e:
            self.log_message("Error setting wavetable property: " + str(e))
            raise

    def _add_wavetable_mod_target(self, track_index, device_index, chain_index,
                                  parameter_name=None, parameter_index=None):
        """Add a parameter to the matrix and report how device.parameters changed.

        The returned before/after parameter names answer whether Live creates
        automatable amount parameters for the new target.
        """
        try:
            track, device = self._resolve_device_in_chain(
                track_index, device_index, chain_index)
            param, _ = self._find_parameter(
                device, name=parameter_name, index=parameter_index)

            modulatable = None
            if hasattr(device, "is_parameter_modulatable"):
                try:
                    modulatable = bool(device.is_parameter_modulatable(param))
                except Exception as e:
                    modulatable = "error: " + str(e)[:60]

            before = [p.name for p in device.parameters]
            targets_before = list(
                getattr(device, "visible_modulation_target_names", []))

            added_index = device.add_parameter_to_modulation_matrix(param)

            after = [p.name for p in device.parameters]
            targets_after = list(
                getattr(device, "visible_modulation_target_names", []))

            return {
                "device_name": device.name,
                "parameter": param.name,
                "is_modulatable": modulatable,
                "added_target_index": added_index,
                "new_parameters": [p for p in after if p not in before],
                "parameter_count_before": len(before),
                "parameter_count_after": len(after),
                "targets_before": targets_before,
                "targets_after": targets_after,
            }
        except Exception as e:
            self.log_message("Error adding modulation target: " + str(e))
            raise

    def _set_wavetable_modulation(self, track_index, device_index, chain_index,
                                  target_index, source, value):
        """Set one matrix cell, if this build of Live allows it."""
        try:
            track, device = self._resolve_device_in_chain(
                track_index, device_index, chain_index)
            sources = self._wavetable_source_map()
            if isinstance(source, str):
                if source not in sources:
                    raise ValueError("Unknown source '{0}'. Known: {1}".format(
                        source, ", ".join(sorted(sources))))
                source_val = sources[source]
            else:
                source_val = int(source)

            setter = getattr(device, "set_modulation_value", None)
            if setter is None:
                raise ValueError(
                    "This build of Live exposes no set_modulation_value; the "
                    "matrix is read-only through the API")
            setter(int(target_index), source_val, float(value))
            return {
                "device_name": device.name,
                "target_index": target_index,
                "source": source,
                "value": float(device.get_modulation_value(
                    int(target_index), source_val)),
            }
        except Exception as e:
            self.log_message("Error setting wavetable modulation: " + str(e))
            raise

    # ------------------------------------------------------------------
    # Session clip properties
    #
    # Clip is a single class: a Session clip and an Arrangement clip are the
    # same object. _set_arrangement_clip_property already exposed these; the
    # Session side only ever had set_clip_name. Same properties, different
    # resolver. These are the controls in Live's Clip panel - Transpose,
    # Clip Gain, Loop Position/Length, Start/End, and clip deactivation.
    # ------------------------------------------------------------------

    SESSION_CLIP_WRITABLE = (
        "name", "muted", "color", "looping", "loop_start", "loop_end",
        "start_marker", "end_marker", "gain", "pitch_coarse", "pitch_fine",
        "warping", "warp_mode", "velocity_amount",
    )

    SESSION_CLIP_READABLE = SESSION_CLIP_WRITABLE + (
        "length", "is_midi_clip", "is_audio_clip", "is_playing", "is_recording",
        "file_path", "signature_numerator", "signature_denominator",
    )

    def _resolve_session_clip(self, track_index, clip_index):
        """Return (track, clip) for a Session slot, or raise."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index {0} out of range (0-{1})".format(
                clip_index, len(track.clip_slots) - 1))
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        return track, clip_slot.clip

    def _get_clip_properties(self, track_index, clip_index):
        """Read every Clip-panel property that applies to this clip.

        Audio-only properties simply do not appear for MIDI clips rather than
        failing the whole call.
        """
        try:
            track, clip = self._resolve_session_clip(track_index, clip_index)
            out = {"track_index": track_index, "clip_index": clip_index}
            for name in self.SESSION_CLIP_READABLE:
                try:
                    value = getattr(clip, name)
                except Exception:
                    continue
                try:
                    if isinstance(value, bool):
                        out[name] = bool(value)
                    elif isinstance(value, (int, float)):
                        out[name] = value
                    else:
                        out[name] = str(value)
                except Exception:
                    pass
            return out
        except Exception as e:
            self.log_message("Error getting clip properties: " + str(e))
            raise

    def _set_clip_property(self, track_index, clip_index, property_name, value):
        """Set one property on a Session clip."""
        try:
            if property_name not in self.SESSION_CLIP_WRITABLE:
                raise ValueError("Property '{0}' not allowed. Allowed: {1}".format(
                    property_name, ", ".join(self.SESSION_CLIP_WRITABLE)))
            track, clip = self._resolve_session_clip(track_index, clip_index)
            before = getattr(clip, property_name, None)
            setattr(clip, property_name, value)
            return {
                "clip_name": clip.name,
                "property": property_name,
                "before": before,
                "value": getattr(clip, property_name),
            }
        except Exception as e:
            self.log_message("Error setting clip property: " + str(e))
            raise

    # ------------------------------------------------------------------
    # Scenes
    #
    # A scene is a row of the Session grid: firing one launches every clip in
    # that row and stops tracks whose slot in the row is empty (unless the slot
    # has no stop button). Per the Live 11.0.5 release notes, writing a scene's
    # tempo or time signature from the Python API also enables that control, so
    # no separate enable flag is needed.
    # ------------------------------------------------------------------

    SCENE_WRITABLE = ("name", "color", "tempo",
                      "time_signature_numerator", "time_signature_denominator")

    def _resolve_scene(self, scene_index):
        scenes = list(self._song.scenes)
        if scene_index < 0 or scene_index >= len(scenes):
            raise IndexError("Scene index {0} out of range (0-{1})".format(
                scene_index, len(scenes) - 1))
        return scenes[scene_index]

    def _get_scenes(self):
        """List every scene with the state needed to pick one."""
        try:
            out = []
            for i, scene in enumerate(self._song.scenes):
                entry = {
                    "index": i,
                    "name": scene.name,
                    "is_empty": bool(scene.is_empty),
                    "is_triggered": bool(scene.is_triggered),
                }
                for opt in ("color", "tempo", "time_signature_numerator",
                            "time_signature_denominator"):
                    try:
                        entry[opt] = getattr(scene, opt)
                    except Exception:
                        pass
                filled = []
                try:
                    for ti, slot in enumerate(scene.clip_slots):
                        if slot.has_clip:
                            filled.append({"track_index": ti,
                                           "clip_name": slot.clip.name})
                except Exception:
                    pass
                entry["clips"] = filled
                out.append(entry)
            return {"scene_count": len(out), "scenes": out}
        except Exception as e:
            self.log_message("Error getting scenes: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Launch a scene: every clip in the row starts, empty slots stop."""
        try:
            scene = self._resolve_scene(scene_index)
            scene.fire()
            return {"index": scene_index, "name": scene.name, "fired": True}
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    def _create_scene(self, index=-1):
        """Insert a scene. -1 appends at the end."""
        try:
            self._song.create_scene(index)
            new_index = len(self._song.scenes) - 1 if index == -1 else index
            scene = self._song.scenes[new_index]
            return {"index": new_index, "name": scene.name,
                    "scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _delete_scene(self, scene_index):
        try:
            scene = self._resolve_scene(scene_index)
            name = scene.name
            self._song.delete_scene(scene_index)
            return {"deleted": True, "index": scene_index, "name": name,
                    "scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error deleting scene: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        try:
            self._resolve_scene(scene_index)
            self._song.duplicate_scene(scene_index)
            return {"duplicated_from": scene_index,
                    "new_index": scene_index + 1,
                    "scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    def _set_scene_property(self, scene_index, property_name, value):
        """Set name / color / tempo / time signature on a scene."""
        try:
            if property_name not in self.SCENE_WRITABLE:
                raise ValueError("Property '{0}' not allowed. Allowed: {1}".format(
                    property_name, ", ".join(self.SCENE_WRITABLE)))
            scene = self._resolve_scene(scene_index)
            before = getattr(scene, property_name, None)
            setattr(scene, property_name, value)
            return {"index": scene_index, "name": scene.name,
                    "property": property_name, "before": before,
                    "value": getattr(scene, property_name)}
        except Exception as e:
            self.log_message("Error setting scene property: " + str(e))
            raise

    def _undo(self):
        """Undo the last action in Live, if there is one."""
        try:
            if not self._song.can_undo:
                return {"undone": False, "reason": "nothing to undo"}
            self._song.undo()
            return {"undone": True, "can_undo": bool(self._song.can_undo),
                    "can_redo": bool(self._song.can_redo)}
        except Exception as e:
            self.log_message("Error undoing: " + str(e))
            raise

    def _redo(self):
        """Redo the last undone action, if there is one."""
        try:
            if not self._song.can_redo:
                return {"redone": False, "reason": "nothing to redo"}
            self._song.redo()
            return {"redone": True, "can_undo": bool(self._song.can_undo),
                    "can_redo": bool(self._song.can_redo)}
        except Exception as e:
            self.log_message("Error redoing: " + str(e))
            raise

    def _write_notes(self, clip, notes):
        """Write notes to a MIDI clip, preferring the non-deprecated API.

        Live logs "Clip.set_notes is deprecated since Live 11.0" on every call
        and points at add_new_notes, which takes MidiNoteSpecification objects
        rather than plain tuples. The Live 11 API dump does not document that
        constructor, so the modern path is attempted and the legacy tuple path
        remains as a fallback. Returns the name of the path actually used.
        """
        specs = None
        try:
            import Live
            spec_cls = Live.Clip.MidiNoteSpecification
            specs = [spec_cls(
                pitch=int(n.get("pitch", 60)),
                start_time=float(n.get("start_time", 0.0)),
                duration=float(n.get("duration", 0.25)),
                velocity=float(n.get("velocity", 100)),
                mute=bool(n.get("mute", False))) for n in notes]
        except Exception as e:
            self.log_message("MidiNoteSpecification unavailable: " + str(e))
            specs = None

        if specs is not None and hasattr(clip, "add_new_notes"):
            try:
                clip.add_new_notes(tuple(specs))
                return "add_new_notes"
            except Exception as e:
                self.log_message("add_new_notes failed, using set_notes: " + str(e))

        live_notes = [(
            int(n.get("pitch", 60)),
            float(n.get("start_time", 0.0)),
            float(n.get("duration", 0.25)),
            int(n.get("velocity", 100)),
            bool(n.get("mute", False))) for n in notes]
        clip.set_notes(tuple(live_notes))
        return "set_notes"

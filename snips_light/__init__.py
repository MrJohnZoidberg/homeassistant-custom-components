import time
import json
import webcolors
import threading

# The domain of your component. Should be equal to the name of your component.
DOMAIN = 'snips_light'

# List of integration names (string) your integration depends upon.
DEPENDENCIES = ['mqtt']


FLASH_LIGHT_ENTITY_ID = 'light.bettbeleuchtung'
ROOMS = {
    'Schlafzimmer': {
        'lights': [
            {'type': 'Bettbeleuchtung', 'entity_id': 'light.bettbeleuchtung'},
            {'type': 'Tischbeleuchtung', 'entity_id': 'light.tischbeleuchtung'}
        ],
        'flash_light_entity_id': 'light.bettbeleuchtung'
    }
}
SNIPS_SITE_IDS = {'bedroom': 'Schlafzimmer'}

COLOR_LISTEN = (0, 0, 255)
COLOR_LOAD = (0, 255, 255)
COLOR_SPEAK = (0, 255, 0)

BRIGHTNESS_BEHAVIOR = 'exp'  # lin or exp
BRIGHTNESS_STEP = 20
BRIGHTNESS_MIN = 2
BRIGHTNESS_MAX = 100


class Light:
    def __init__(self, hass, mqtt, entity_id, room):
        self.hass = hass
        self.mqtt = mqtt
        self.entity_id = entity_id
        self.room = room
        self.flash_status = False
        self.saved_state = None
        self.saved_rgb_color = None
        self.saved_brightness = None
        self.current_rgb_color = None

    def store_light_attributes(self):
        self.saved_rgb_color = self.hass.states.get(self.entity_id).attributes['rgb_color']
        self.saved_brightness = self.hass.states.get(self.entity_id).attributes['brightness']

    def start_flashing(self):
        self.flash_status = True
        success = self.first_flash()
        if success:
            self.mqtt.publish('hass/one_flash_finished', json.dumps({'entity_id': self.entity_id}))
        else:
            self.flash_status = False

    def first_flash(self):
        result = self.hass.states.get(self.entity_id)
        if not result:
            return False
        else:
            self.saved_state = result.state
        if self.saved_state == 'off':
            data = {'entity_id': self.entity_id,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_on', data)
            time.sleep(0.1)
            self.store_light_attributes()
            data = {'entity_id': self.entity_id,
                    'rgb_color': self.current_rgb_color,
                    'transition': 0.1}
            self.hass.services.call('light', 'turn_on', data)
            time.sleep(0.3)
        else:
            self.store_light_attributes()
            data = {'entity_id': self.entity_id,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_off', data)
            time.sleep(0.4)
        return True

    def one_flash(self):
        current_state = self.hass.states.get(self.entity_id).state
        if current_state == 'on':
            data = {'entity_id': self.entity_id,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_off', data, True)
        else:
            data = {'entity_id': self.entity_id,
                    'rgb_color': self.current_rgb_color,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_on', data, True)
        time.sleep(0.4)
        self.mqtt.publish('hass/one_flash_finished', json.dumps({'entity_id': self.entity_id}))

    def last_flash(self):
        if self.saved_state == 'off':
            data = {'entity_id': self.entity_id,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_on', data, True)
            time.sleep(0.3)
            data = {'entity_id': self.entity_id,
                    'rgb_color': self.saved_rgb_color,
                    'brightness': self.saved_brightness,
                    'transition': 0.1}
            self.hass.services.call('light', 'turn_on', data, False)
            time.sleep(0.1)
            data = {'entity_id': self.entity_id,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_off', data, False)
        else:
            current_state = self.hass.states.get(self.entity_id).state
            if current_state == 'on':
                data = {'entity_id': self.entity_id,
                        'transition': 0.3}
                self.hass.services.call('light', 'turn_off', data, False)
                time.sleep(0.4)
            data = {'entity_id': self.entity_id,
                    'rgb_color': self.saved_rgb_color,
                    'brightness': self.saved_brightness,
                    'transition': 0.3}
            self.hass.services.call('light', 'turn_on', data, True)


class SnipsLight:
    def __init__(self, hass, mqtt):
        self.lights = dict()
        self.sunrise_threads = dict()
        for room_name in ROOMS:
            for light_dict in ROOMS[room_name]['lights']:
                entity_id = light_dict['entity_id']
                self.lights[entity_id] = Light(hass, mqtt, entity_id, room_name)


def setup(hass, config):
    mqtt = hass.components.mqtt
    flash_light_entity_id = config[DOMAIN].get('flash_entity_id', FLASH_LIGHT_ENTITY_ID)
    snipslight = SnipsLight(hass, mqtt)

    def end_session(session_id, text=None):
        if text:
            data = {'text': text, 'sessionId': session_id}
        else:
            data = {'sessionId': session_id}
        mqtt.publish('hermes/dialogueManager/endSession', json.dumps(data))

    def continue_session(session_id, text, intent_filter=None, custom_data=None, send_error=None, slot=None):
        data = {'sessionId': session_id, 'text': text}
        if intent_filter:
            data['intentFilter'] = intent_filter
        if custom_data:
            data['customData'] = custom_data
        if send_error:
            data['sendIntentNotRecognized'] = True
        if slot:
            data['slot'] = slot
        mqtt.publish('hermes/dialogueManager/continueSession', json.dumps(data))

    def one_flash_finished_received(msg):
        data = json.loads(msg.payload)
        light = snipslight.lights[data['entity_id']]
        if light.flash_status:
            light.one_flash()
        else:
            light.last_flash()

    def get_flashlight_obj(data):
        site_id = data['siteId']
        if site_id not in SNIPS_SITE_IDS or SNIPS_SITE_IDS[site_id] not in ROOMS \
                or not ROOMS[SNIPS_SITE_IDS[site_id]].get('flash_light_entity_id'):
            return None
        entity_id = ROOMS[SNIPS_SITE_IDS[site_id]].get('flash_light_entity_id')
        light = snipslight.lights[entity_id]
        return light

    def start_listening_received(msg):
        light = get_flashlight_obj(json.loads(msg.payload))
        if not light:
            return
        light.current_rgb_color = COLOR_LISTEN
        if not light.flash_status:
            light.start_flashing()

    def text_captured_received(msg):
        light = get_flashlight_obj(json.loads(msg.payload))
        if not light:
            return
        if light.flash_status:
            light.current_rgb_color = COLOR_LOAD

    def tts_say_received(msg):
        light = get_flashlight_obj(json.loads(msg.payload))
        if not light:
            return
        light.current_rgb_color = COLOR_SPEAK
        if not light.flash_status:
            light.start_flashing()

    def session_ended_received(msg):
        light = get_flashlight_obj(json.loads(msg.payload))
        if not light:
            return
        if light.flash_status:
            light.flash_status = False

    def sunrise_thread(lights, minutes, room):
        def calc_brightness(duration_mins, passed_secs):
            return 255 / (duration_mins * 60) * passed_secs
        brightness = 0
        passed_seconds = 0
        while brightness < 255 and room in snipslight.sunrise_threads:
            new_brightness = calc_brightness(minutes, passed_seconds)
            if new_brightness != brightness and not lights[0].flash_status:
                brightness = new_brightness
                data = {'entity_id': lights[0].entity_id,
                        'brightness': brightness,
                        'rgb_color': (255, 100, 0)}
                hass.services.call('light', 'turn_on', data)
            time.sleep(1)
            passed_seconds += 1

    def msg_start_sunrise(msg):
        data = json.loads(msg.payload)
        room = data['room']
        if room not in ROOMS:
            return
        lights = [snipslight.lights[light_dict['entity_id']] for light_dict in ROOMS[room]['lights']]
        minutes = data['minutes']
        snipslight.sunrise_threads[room] = threading.Thread(target=sunrise_thread, args=(lights, minutes, room))
        snipslight.sunrise_threads[room].start()

    def get_slot_dict(payload_data):
        slot_dict = {}
        for slot in payload_data['slots']:
            slot_dict[slot['slotName']] = slot['value']['value']
        return slot_dict

    def get_entity_ids(slot_dict, site_id):
        # requested room
        if 'location' in slot_dict and slot_dict['location'] in ROOMS:
            entity_ids = list()
            for light_dict in ROOMS[slot_dict['location']]['lights']:
                if 'type' in slot_dict:
                    if light_dict['type'] == slot_dict['type']:
                        entity_ids.append(light_dict['entity_id'])
                else:
                    entity_ids.append(light_dict['entity_id'])

        # all rooms
        elif 'location' in slot_dict and slot_dict['location'] == "alle" and ROOMS:
            entity_ids = list()
            for room_name in ROOMS:
                for light_dict in ROOMS[room_name]['lights']:
                    entity_ids.append(light_dict['entity_id'])

        # room of request
        elif 'location' in slot_dict and slot_dict['location'] == "hier" or \
                site_id in SNIPS_SITE_IDS and SNIPS_SITE_IDS[site_id] in ROOMS:
            entity_ids = list()
            for light_dict in ROOMS[SNIPS_SITE_IDS[site_id]]['lights']:
                if 'type' in slot_dict:
                    if light_dict['type'] == slot_dict['type']:
                        entity_ids.append(light_dict['entity_id'])
                else:
                    entity_ids.append(light_dict['entity_id'])
        else:
            return None, "Nicht richtig konfiguriert."

        if not entity_ids:
            return None, "Die gewünschten Lampen gibt es nicht."
        else:
            return entity_ids, None

    def get_rgb_color(css_color):
        try:
            named_tuple = webcolors.name_to_rgb(css_color)
            rgb_color = (named_tuple.red, named_tuple.green, named_tuple.blue)
        except ValueError:
            return None, "Ich habe die Farbe nicht verstanden."
        return rgb_color, None

    def is_single_other_room(room, request_siteid):
        is_same_room = request_siteid in SNIPS_SITE_IDS and room == SNIPS_SITE_IDS[request_siteid]
        result = not room or room in ["alle", "hier"] or is_same_room
        return not result

    def lights_off_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)
            return

        for entity_id in entity_ids:
            light = snipslight.lights[entity_id]
            if light.room in snipslight.sunrise_threads:
                del snipslight.sunrise_threads[light.room]
            if entity_id == flash_light_entity_id and light.flash_status:
                light.saved_state = 'off'
            else:
                data = {'entity_id': entity_id,
                        'transition': 0.3}
                hass.services.call('light', 'turn_off', data)

        req_room = slot_dict.get('location')
        if is_single_other_room(req_room, payload_data['siteId']):
            lights_on = [light_dict['entity_id'] for light_dict in ROOMS[req_room]['lights']
                         if hass.states.get(light_dict['entity_id']).state == "on"]
            if lights_on:
                answer = f"Im Raum {req_room} sind noch weitere Lichter an."
            else:
                answer = f"Im Raum {req_room} wurde das Licht vollständig ausgeschaltet."
        else:
            answer = None

        end_session(payload_data['sessionId'], answer)

    def lights_on_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)
            return

        if 'brightness' in slot_dict:
            if int(slot_dict['brightness']) > BRIGHTNESS_MAX:
                slot_dict['brightness'] = BRIGHTNESS_MAX
            elif int(slot_dict['brightness']) < BRIGHTNESS_MIN:
                slot_dict['brightness'] = BRIGHTNESS_MIN
            brightness = int(slot_dict['brightness'] * 2.55)
        else:
            brightness = None
        if 'color' in slot_dict:
            rgb_color, error = get_rgb_color(slot_dict['color'])
            if error:
                end_session(payload_data['sessionId'], error)
                return
        else:
            rgb_color = None

        for entity_id in entity_ids:
            light = snipslight.lights[entity_id]
            if entity_id == flash_light_entity_id and light.flash_status:
                light.saved_state = 'on'
                if brightness:
                    light.saved_brightness = brightness
                if rgb_color:
                    light.saved_rgb_color = rgb_color
            else:
                data = {'entity_id': entity_id,
                        'transition': 0.3}
                if brightness:
                    data['brightness'] = brightness
                if rgb_color:
                    data['rgb_color'] = rgb_color
                hass.services.call('light', 'turn_on', data)

        req_room = slot_dict.get('location')
        if is_single_other_room(req_room, payload_data['siteId']):
            answer = f"Im Raum {req_room} wurde das Licht angeschaltet."
        else:
            answer = None

        end_session(payload_data['sessionId'], answer)

    def color_change_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        if payload_data['customData'] is not None:
            entity_ids = payload_data['customData'].split(';')
        else:
            entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
            if error:
                end_session(payload_data['sessionId'], error)
                return

        if 'color' not in slot_dict:
            continue_session(payload_data['sessionId'], "Welche Farbe?", ['domi:FarbeWechseln'],
                             custom_data=";".join(entity_ids), slot='color')
            return

        rgb_color, error = get_rgb_color(slot_dict['color'])
        if error:
            end_session(payload_data['sessionId'], error)
            return

        for entity_id in entity_ids:
            light = snipslight.lights[entity_id]
            if entity_id == flash_light_entity_id and light.flash_status:
                light.saved_rgb_color = rgb_color
            else:
                state = hass.states.get(entity_id).state
                if state == "on":
                    data = {'entity_id': entity_id,
                            'rgb_color': rgb_color,
                            'transition': 0.3}
                    hass.services.call('light', 'turn_on', data)
                else:
                    light.saved_rgb_color = rgb_color

        if is_single_other_room(slot_dict.get('location'), payload_data['siteId']):
            answer = f"Im Raum {slot_dict.get('location')} wurde die Farbe gewechselt."
        else:
            answer = None

        end_session(payload_data['sessionId'], answer)

    def brightness_action(slot_dict, brightness):
        if slot_dict['action'] == 'higher':
            if BRIGHTNESS_BEHAVIOR == 'lin':
                brightness += int(BRIGHTNESS_STEP * 2.55)
            else:
                brightness = int(brightness + (brightness * BRIGHTNESS_STEP * 0.01))
        elif slot_dict['action'] == 'lower':
            if BRIGHTNESS_BEHAVIOR == 'lin':
                brightness -= int(BRIGHTNESS_STEP * 2.55)
            else:
                brightness = int(brightness - (brightness * BRIGHTNESS_STEP * 0.01))
        elif slot_dict['action'] == 'highest':
            brightness = int(BRIGHTNESS_MAX * 2.55)
        elif slot_dict['action'] == 'lowest':
            brightness = int(BRIGHTNESS_MIN * 2.55)
        return brightness

    def dim_lights_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)
            return

        for entity_id in entity_ids:
            light = snipslight.lights[entity_id]
            brightness = None
            if 'brightness' in slot_dict:
                brightness = int(slot_dict['brightness'] * 2.55)
            elif 'action' in slot_dict:
                if entity_id == flash_light_entity_id and light.flash_status:
                    brightness = brightness_action(slot_dict, light.saved_brightness)
                elif hass.states.get(entity_id).state == 'on':
                    brightness = brightness_action(slot_dict, hass.states.get(entity_id).attributes['brightness'])
                elif hass.states.get(entity_id).state == 'off':
                    brightness = brightness_action(slot_dict, 0)
                    if brightness <= 0:
                        brightness = None
            else:
                end_session(payload_data['sessionId'], "Du hast keinen Wert gesagt.")
                return

            if brightness:
                if brightness > int(BRIGHTNESS_MAX * 2.55):
                    brightness = int(BRIGHTNESS_MAX * 2.55)
                elif brightness < int(BRIGHTNESS_MIN * 2.55):
                    brightness = int(BRIGHTNESS_MIN * 2.55)

                if entity_id == flash_light_entity_id and light.flash_status:
                    light.saved_state = 'on'
                    light.saved_brightness = brightness
                else:
                    data = {'entity_id': entity_id,
                            'brightness': brightness,
                            'transition': 0.3}
                    hass.services.call('light', 'turn_on', data)
        end_session(payload_data['sessionId'])

    mqtt.subscribe('hermes/asr/startListening', start_listening_received)
    mqtt.subscribe('hermes/asr/textCaptured', text_captured_received)
    mqtt.subscribe('hermes/tts/say', tts_say_received)
    mqtt.subscribe('hermes/dialogueManager/sessionEnded', session_ended_received)
    mqtt.subscribe('hermes/intent/domi:LampenAusSchalten', lights_off_received)
    mqtt.subscribe('hermes/intent/domi:LampenAnSchalten', lights_on_received)
    mqtt.subscribe('hermes/intent/domi:FarbeWechseln', color_change_received)
    mqtt.subscribe('hermes/intent/domi:LichtDimmen', dim_lights_received)
    mqtt.subscribe('hass/one_flash_finished', one_flash_finished_received)
    mqtt.subscribe('external/alarmclock/sunriseStart', msg_start_sunrise)

    # Return boolean to indicate that initialization was successfully.
    return True

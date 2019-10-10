import time
import json
import webcolors

# The domain of your component. Should be equal to the name of your component.
DOMAIN = 'snips_light'

# List of integration names (string) your integration depends upon.
DEPENDENCIES = ['mqtt']


FLASH_LIGHT_ENTITY_ID = 'light.tischbeleuchtung'
ROOMS = {'Schlafzimmer': [{'type': 'Bettbeleuchtung', 'entity_id': 'light.bettbeleuchtung'},
                          {'type': 'Tischbeleuchtung', 'entity_id': 'light.tischbeleuchtung'}]}
SNIPS_SITE_IDS = {'default': 'Schlafzimmer'}

COLOR_LISTEN = (0, 0, 255)
COLOR_LOAD = (0, 255, 255)
COLOR_SPEAK = (0, 255, 0)

BRIGHTNESS_BEHAVIOR = 'exp'  # lin or exp
BRIGHTNESS_STEP = 20
BRIGHTNESS_MIN = 2
BRIGHTNESS_MAX = 100


class Flashing:
    def __init__(self):
        self.flash_status = False
        self.saved_state = None
        self.saved_rgb_color = None
        self.saved_brightness = None
        self.current_rgb_color = None

def setup(hass, config):
    mqtt = hass.components.mqtt
    flash_light_entity_id = config[DOMAIN].get('flash_entity_id', FLASH_LIGHT_ENTITY_ID)
    fl = Flashing()

    def store_light_attributes():
        fl.saved_rgb_color = hass.states.get(flash_light_entity_id).attributes['rgb_color']
        fl.saved_brightness = hass.states.get(flash_light_entity_id).attributes['brightness']

    def first_flash():
        fl.saved_state = hass.states.get(flash_light_entity_id).state
        if fl.saved_state == 'off':
            data = {'entity_id': flash_light_entity_id,
                    'transition': 0.3}
            hass.services.call('light', 'turn_on', data)
            time.sleep(0.1)
            store_light_attributes()
            data = {'entity_id': flash_light_entity_id,
                    'rgb_color': fl.current_rgb_color,
                    'transition': 0.1}
            hass.services.call('light', 'turn_on', data)
            time.sleep(0.3)
        else:
            store_light_attributes()
            data = {'entity_id': flash_light_entity_id,
                    'transition': 0.3}
            hass.services.call('light', 'turn_off', data)
            time.sleep(0.4)

    def last_flash(current_state):
        if fl.saved_state == 'off':
            data = {'entity_id': flash_light_entity_id,
                    'transition': 0.3}
            hass.services.call('light', 'turn_on', data, True)
            time.sleep(0.3)
            data = {'entity_id': flash_light_entity_id,
                    'rgb_color': fl.saved_rgb_color,
                    'brightness': fl.saved_brightness,
                    'transition': 0.1}
            hass.services.call('light', 'turn_on', data, False)
            time.sleep(0.1)
            data = {'entity_id': flash_light_entity_id,
                    'transition': 0.3}
            hass.services.call('light', 'turn_off', data, False)
        else:
            if current_state == 'on':
                data = {'entity_id': flash_light_entity_id,
                        'transition': 0.3}
                hass.services.call('light', 'turn_off', data, False)
                time.sleep(0.4)
            data = {'entity_id': flash_light_entity_id,
                    'rgb_color': fl.saved_rgb_color,
                    'brightness': fl.saved_brightness,
                    'transition': 0.3}
            hass.services.call('light', 'turn_on', data, True)

    def start_flashing():
        first_flash()
        fl.flash_status = True
        one_flash_finished_received(None)

    def end_session(session_id, text=None):
        if text:
            data = {'text': text, 'sessionId': session_id}
        else:
            data = {'sessionId': session_id}
        mqtt.publish('hermes/dialogueManager/endSession', json.dumps(data))

    def one_flash_finished_received(msg):
        current_state = hass.states.get(flash_light_entity_id).state
        if fl.flash_status:
            if current_state == 'on':
                data = {'entity_id': flash_light_entity_id,
                        'transition': 0.3}
                hass.services.call('light', 'turn_off', data, True)
            else:
                data = {'entity_id': flash_light_entity_id,
                        'rgb_color': fl.current_rgb_color,
                        'transition': 0.3}
                hass.services.call('light', 'turn_on', data, True)
            time.sleep(0.4)
            mqtt.publish('hass/one_flash_finished', None)
        else:
            last_flash(current_state)

    def start_listening_received(msg):
        fl.current_rgb_color = COLOR_LISTEN
        if not fl.flash_status:
            start_flashing()

    def text_captured_received(msg):
        fl.current_rgb_color = COLOR_LOAD

    def tts_say_received(msg):
        fl.current_rgb_color = COLOR_SPEAK
        if not fl.flash_status:
            start_flashing()

    def session_ended_received(msg):
        fl.flash_status = False

    def get_slot_dict(payload_data):
        slot_dict = {}
        for slot in payload_data['slots']:
            slot_dict[slot['slotName']] = slot['value']['value']
        return slot_dict

    def get_entity_ids(slot_dict, site_id):
        entity_ids = []
        if 'location' in slot_dict and slot_dict['location'] in ROOMS:
            for light_dict in ROOMS[slot_dict['location']]:
                if 'type' in slot_dict:
                    if light_dict['type'] == slot_dict['type']:
                        entity_ids.append(light_dict['entity_id'])
                else:
                    entity_ids.append(light_dict['entity_id'])
        elif 'location' in slot_dict and slot_dict['location'] == "alle" and ROOMS:
            for room_name in ROOMS:
                for light_dict in ROOMS[room_name]:
                    entity_ids.append(light_dict['entity_id'])
        elif site_id in SNIPS_SITE_IDS and SNIPS_SITE_IDS[site_id] in ROOMS:
            for light_dict in ROOMS[SNIPS_SITE_IDS[site_id]]:
                if 'type' in slot_dict:
                    if light_dict['type'] == slot_dict['type']:
                        entity_ids.append(light_dict['entity_id'])
                else:
                    entity_ids.append(light_dict['entity_id'])
        else:
            return None, "Nicht richtig konfiguriert."
        if not entity_ids:
            return None, "Die gewünschten Lampen gibt es nicht."
        return entity_ids, None

    def get_rgb_color(css_color):
        named_tuple = webcolors.name_to_rgb(css_color)
        try:
            rgb_color = (named_tuple.red, named_tuple.green, named_tuple.blue)
        except ValueError:
            return None, "Ich habe die Farbe nicht verstanden."
        return rgb_color, None

    def lights_off_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)

        for entity_id in entity_ids:
            if entity_id == flash_light_entity_id and fl.flash_status:
                fl.saved_state = 'off'
            else:
                data = {'entity_id': entity_id,
                        'transition': 0.3}
                hass.services.call('light', 'turn_off', data)
        end_session(payload_data['sessionId'])

    def lights_on_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)

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
        else:
            rgb_color = None

        for entity_id in entity_ids:
            if entity_id == flash_light_entity_id and fl.flash_status:
                fl.saved_state = 'on'
                if brightness:
                    fl.saved_brightness = brightness
                if rgb_color:
                    fl.saved_rgb_color = rgb_color
            else:
                data = {'entity_id': entity_id,
                        'transition': 0.3}
                if brightness:
                    data['brightness'] = brightness
                if rgb_color:
                    data['rgb_color'] = rgb_color
                hass.services.call('light', 'turn_on', data)
        end_session(payload_data['sessionId'])

    def color_change_received(msg):
        payload_data = json.loads(msg.payload)
        slot_dict = get_slot_dict(payload_data)

        entity_ids, error = get_entity_ids(slot_dict, payload_data['siteId'])
        if error:
            end_session(payload_data['sessionId'], error)

        rgb_color, error = get_rgb_color(slot_dict['color'])
        if error:
            end_session(payload_data['sessionId'], error)

        for entity_id in entity_ids:
            if entity_id == flash_light_entity_id and fl.flash_status:
                fl.saved_state = 'on'
                fl.saved_rgb_color = rgb_color
            else:
                data = {'entity_id': entity_id,
                        'rgb_color': rgb_color,
                        'transition': 0.3}
                hass.services.call('light', 'turn_on', data)
        end_session(payload_data['sessionId'])

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
            brightness = None
            if 'brightness' in slot_dict:
                brightness = int(slot_dict['brightness'] * 2.55)
            elif 'action' in slot_dict:
                if entity_id == flash_light_entity_id and fl.flash_status:
                    brightness = brightness_action(slot_dict, fl.saved_brightness)
                elif hass.states.get(entity_id).state == 'on':
                    brightness = brightness_action(slot_dict, hass.states.get(entity_id).attributes['brightness'])
                elif hass.states.get(entity_id).state == 'off':
                    brightness = brightness_action(slot_dict, 0)
                    if brightness <= 0:
                        brightness = None
            else:
                end_session(payload_data['sessionId'], "Du hast keinen Wert gesagt.")
                return

            if brightness > int(BRIGHTNESS_MAX * 2.55):
                brightness = int(BRIGHTNESS_MAX * 2.55)
            elif brightness < int(BRIGHTNESS_MIN * 2.55):
                brightness = int(BRIGHTNESS_MIN * 2.55)

            if brightness:
                if entity_id == flash_light_entity_id and fl.flash_status:
                    fl.saved_state = 'on'
                    fl.saved_brightness = brightness
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
    mqtt.subscribe('hass/one_flash_finished', one_flash_finished_received)
    mqtt.subscribe('hermes/intent/domi:LampenAusSchalten', lights_off_received)
    mqtt.subscribe('hermes/intent/domi:LampenAnSchalten', lights_on_received)
    mqtt.subscribe('hermes/intent/domi:FarbeWechseln', color_change_received)
    mqtt.subscribe('hermes/intent/domi:LichtDimmen', dim_lights_received)

    # Return boolean to indicate that initialization was successfully.
    return True

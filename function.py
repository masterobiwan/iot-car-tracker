# Download the helper library from https://www.twilio.com/docs/python/install
from twilio.rest import Client
import logging
import time
import boto3
import os
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

battery_threshold = 3.63

def my_logging_handler(event, context):
    logger.info('Event data: {}'.format(event))

def hexa_to_binary(payload, spec='b'):
    integer = int(payload, 16)
    return format(integer, spec)

def parse_status(binary):
    status_int = int(binary[0])
    movement_int = int(binary[1])
    battery_voltage = int(binary[2:], 2)/1000
    if status_int == 0:
        status_type = 'keep alive'
    elif status_int == 1:
        status_type = 'alarm'
    else:
        logger.error('Unexpected value found: {}. Should be 0 or 1.').format(status_int)
    if movement_int == 0:
        movement = 'stopped'
    elif movement_int == 1:
        movement = 'moving'
    else:
        logger.error('Unexpected value found: {}. Should be 0 or 1.').format(movement_int)
    return {
        "status": status_type,
        "movement": movement,
        "battery": battery_voltage
    }

def parse_geoloc(binary):
    lat_deg = int(binary[0:8], 2)
    lat_min = int(binary[8:14], 2)
    lat_sec = int(binary[14:31], 2)/100000*60
    lat_hem = "S" if int(binary[31], 2) == 0 else "N"
    long_deg = int(binary[32:40], 2)
    long_min = int(binary[40:46], 2)
    long_sec = int(binary[46:63], 2)/100000*60
    long_hem = "W" if int(binary[63], 2) == 0 else "E"
    sign_lat_hem = 1 if lat_hem == "N" else -1
    sign_long_hem = 1 if long_hem == "E" else -1
    return {
        "lat_text": "{deg}°{minute}'{sec}\"{hem}".format(deg=lat_deg,minute=lat_min,sec=lat_sec,hem=lat_hem),
        "long_text": "{deg}°{minute}'{sec}\"{hem}".format(deg=long_deg,minute=long_min,sec=long_sec,hem=long_hem),
        "lat": sign_lat_hem*(lat_deg + (lat_min/60) + (lat_sec/3600)),
        "long": sign_long_hem*(long_deg + (long_min/60) + (long_sec/3600))
    }

# Your Account Sid and Auth Token from twilio.com/console
account_sid = os.environ['ACCOUNT_SID']
auth_token = os.environ['AUTH_TOKEN']

# device phone number mapping
phone_conf = {
    "224720": "+33689852884"
}

def main(event, context):

    my_logging_handler(event, context)
    
    did_hex = event["device"]
    time_msg = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(event["time"])))
    logger.info('Received message from device {did} at {time_msg}'.format(did=did_hex,time_msg=time_msg))

    payload = event["data"]
    payload_binary = hexa_to_binary(payload)

    # Init dynamodb service resource
    dynamodb = boto3.resource('dynamodb')

    if len(payload_binary) == 16:
        data = parse_status(payload_binary)
        logger.info('Parsed data: {data}'.format(data=data))
        table = dynamodb.Table('battery')
        table.put_item(Item={'did': int(event["device"]), 'time_msg': time_msg, 'voltage': Decimal(str(data["battery"]))})

        if data["status"] == "alarm" and data["movement"] == "moving":
            # Generate phone call
            client = Client(account_sid, auth_token)
            
            call = client.calls.create(
                url='http://castelnajac.fr/twilio/call_config.xml',
                to=phone_conf[did_hex],
                from_='+33567349937'
            )
            
            logger.info("Call id: {cid}".format(cid=call.sid))

        if data["battery"] <= battery_threshold:
            client = boto3.client('ses')
            response = client.send_email(Source='bcarne@castelnajac.fr', Destination={'ToAddresses': ['bcarne@castelnajac.fr']}, Message={'Subject': {'Data': '[Car Tracker] Low battery'}, 'Body': {'Html': {'Data': "Battery level ({bat}) is lower than {thrs}. Please recharge as soon as possible.".format(thrs=battery_threshold,bat=str(data["battery"]))}}})


    elif len(payload_binary) >= 60:
        payload_binary = hexa_to_binary(payload, spec='0>88b')
        parsed = False
        # Parse gps data
        try:
            data = parse_geoloc(payload_binary)

            logger.info('Parsed data: {data}'.format(data=data))

            parsed = True

            #try:
            #    # Generate sms with position link
            #    client = Client(account_sid, auth_token)

            #    message = client.messages.create(
            #            body="Device {did} position computed: https://www.google.com/maps/place/{lat}+{lng}".format(did=did_hex,lat=data['lat_text'],lng=data['long_text']),
            #        to=phone_conf[did_hex],
            #        from_='+33567349937'
            #    )

            #    print(message.sid)
            #except Exception as e:
            #    logger.error('Could not send sms: {}'.format(e))
            
        except:
            logger.error('Could not parse binary: {}'.format(payload_binary))

        if parsed:
            client = boto3.client('ses')
            url = "https://www.google.com/maps/place/{lat}+{lng}".format(lat=data['lat_text'], lng=data['long_text'])
            response = client.send_email(Source='bcarne@castelnajac.fr', Destination={'ToAddresses': ['bcarne@castelnajac.fr']}, Message={'Subject': {'Data': '[Car Tracker] New position'}, 'Body': {'Html': {'Data': "New position received from device {did}. You will find it  <a href={url}>here</a>.".format(did=did_hex, url=url)}}})
            table = dynamodb.Table('position')
            table.put_item(Item={'did': int(event["device"]), 'time_msg': time_msg, 'source': 'gps', 'lat': Decimal(str(data["lat"])), 'lng': Decimal(str(data["long"]))})
    else:
        logger.warn('Payload type not yet supported: {}'.format(payload_binary))


## Test data
## alarm moving
#event = {
#    'device': '224720',
#    'time': '1552137233',
#    'data': 'cfd2'
#}
#context = []
## alarm stopped
#event = {
#    'device': '224720',
#    'time': '1552137671',
#    'data': '8fda'
#}
#context = []
# geolocation frame
#event = {
#    'device': '224720',
#    'time': '1553260256',
#    'data': '2b82ee3901793f7100df21'
#}
#context = []
#main(event, context)

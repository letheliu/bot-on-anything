import werobot
from config import channel_conf
from common import const
from common.log import logger
from channel.channel import Channel
from concurrent.futures import ThreadPoolExecutor
import io
import requests

robot = werobot.WeRoBot(token=channel_conf(const.WECHAT_MP).get('token'))
thread_pool = ThreadPoolExecutor(max_workers=8)

@robot.text
def hello_world(msg):
    logger.info('[WX_Public] receive public msg: {}, userId: {}'.format(msg.content, msg.source))
    return WechatServiceAccount().handle(msg)


class WechatServiceAccount(Channel):
    def startup(self):
        logger.info('[WX_Public] Wechat Public account service start!')
        robot.config['PORT'] = channel_conf(const.WECHAT_MP).get('port')
        robot.config["APP_ID"] = channel_conf(const.WECHAT_MP).get('app_id')
        robot.config["APP_SECRET"] = channel_conf(const.WECHAT_MP).get('app_secret')
        robot.config["ENCODING_AES_KEY"] = channel_conf(const.WECHAT_MP).get('app_aes_key')
        robot.config['HOST'] = '0.0.0.0'
        robot.run()

    def handle(self, msg, count=0):
        context = {}
        context['from_user_id'] = msg.source
        thread_pool.submit(self._do_send, msg.content, context)
        return "正在思考中..."


    def _do_send(self, query, context):
        reply_text = super().build_reply_content(query, context)
        logger.info('[WX_Public] reply content: {}, openID: {}'.format(reply_text, context['from_user_id']))
        client = robot.client
        client.send_text_message(context['from_user_id'], reply_text)
        
    def send_text(self, content, context):
        client  = robot.client
        from_user_id = context['args'].get('from_user_id',  None)
        if from_user_id is None:
            return
        client.send_text_message(from_user_id, content)

    def send_image(self, img_url, context):
        reply_user_id = context['args'].get('from_user_id',  None)
        if reply_user_id is None:
            return
        logger.info('[WX_Public] reply content: {}'.format(img_url))
        if not img_url:
            client = robot.client
            client.send_text_message(reply_user_id, '抱歉，图片生成错误')
            return
        # 图片下载
        pic_res = requests.get(img_url, stream=True)
        image_storage = io.BytesIO()
        for block in pic_res.iter_content(1024):
            image_storage.write(block)
        image_storage.seek(0)
        image_storage.name = "temp.png"

        # 图片发送
        logger.info('[WX] sendImage, receiver={}'.format(reply_user_id))
        client = robot.client
        return_json = client.upload_media('image', image_storage)
        media_id = return_json["media_id"]
        client.send_image_message(reply_user_id, media_id)

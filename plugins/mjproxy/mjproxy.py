# encoding:utf-8
import threading
import plugins

from plugins import *
from common import functions
from config import channel_conf
from config import channel_conf_val
from common import const
from common.log import logger
from common.expired_dict import ExpiredDict

from apscheduler.schedulers.blocking import BlockingScheduler
import requests
from channel.wechat.wechat_mp_service_channel import WechatServiceAccount


@plugins.register(name="MjProxy", desire_priority=91, hidden=False, desc="lx plugin that use mj", version="0.1", author="Lethe")
class MjProxy(Plugin):
    def __init__(self):
      super().__init__()
      self.handlers[Event.ON_HANDLE_CONTEXT] = self.handle_query
      self.handlers[Event.ON_BRIDGE_HANDLE_CONTEXT] = self.handle_query
      
      self.proxy_server = "http://127.0.0.1:8080/mj"
      self.proxy_api_secret = ""
      self.task_id_dict = ExpiredDict(60 * 60)
      self.cmd_dict = ExpiredDict(60 * 60)
      self.context_dict = ExpiredDict(60 * 60)
      
      self.channel = WechatServiceAccount()
      
      scheduler = BlockingScheduler()
      scheduler.add_job(self.query_task_result, 'interval', seconds=10)
      # 创建并启动一个新的线程来运行调度器
      thread = threading.Thread(target=scheduler.start)
      thread.start()
      logger.info("[Midjourney] inited")

    def handle_query(self, e_context: EventContext):
      # if self.channel is None:
      #   self.channel = e_context['channel']
      old_context = e_context
      result = None
      content = e_context['context']
      state = content + e_context['args'].get('from_user_id', "")
      
      if content.startswith("/imagine "):
        logger.info("[===lethe===] 进入imagine指令流程 {}".format(state))
        state = content[9:] + e_context['args'].get('from_user_id', "")
        result = self.post_json('/submit/imagine', {'prompt': content[9:], 'state': state})
      elif content.startswith("/up "):
        arr = content[4:].split()
        try:
          task_id = arr[0]
          index = int(arr[1])
        except Exception as e:
          e_context['reply'] = '❌ 您的任务提交失败\nℹ️ 参数错误'
          e_context.action= EventAction.BREAK_PASS
          return
        # 获取任务
        task = self.get_task(task_id)
        if task is None:
          e_context['reply'] = '❌ 您的任务提交失败\nℹ️ 任务ID不存在'
          e_context.action= EventAction.BREAK_PASS
          return
        if index > len(task['buttons']):
          e_context['reply'] = '❌ 您的任务提交失败\nℹ️ 按钮序号不正确'
          e_context.action = EventAction.BREAK_PASS
          return
        # 获取按钮
        button = task['buttons'][index - 1]
        if button['label'] == 'Custom Zoom':
          e_context['reply'] = '❌ 您的任务提交失败\nℹ️ 暂不支持自定义变焦'
          e_context.action = EventAction.BREAK_PASS
          return
        result = self.post_json('/submit/action', {'customId': button['customId'], 'taskId': task_id, 'state': state})
      elif content.startswith("/img2img "):
        self.cmd_dict[msg.actual_user_id] = content
        e_context['reply'] = '请给我发一张图片作为垫图'
        e_context.action = EventAction.BREAK_PASS
        return
      elif content == "/describe":
        self.cmd_dict[msg.actual_user_id] = content
        e_context['reply'] = '请给我发一张图片用于图生文'
        e_context.action = EventAction.BREAK_PASS
        return
      elif content.startswith("/shorten "):
        result = self.handle_shorten(content[9:], state)
      else:
        e_context.action = EventAction.CONTINUE
        return e_context
      code = result.get("code")
      if code == 1:
        task_id = result.get("result")
        self.add_task(task_id)
        self.add_context(task_id, old_context)
        e_context['reply'] = '✅ 您的任务已提交\n🚀 正在快速处理中，请稍后\n📨 任务ID: ' + task_id
      elif code == 22:
        self.add_task(result.get("result"))
        e_context['reply'] = '✅ 您的任务已提交\n⏰ ' + result.get("description")
      else:
        e_context['reply'] = '❌ 您的任务提交失败\nℹ️ ' + result.get("description")
      e_context.action = EventAction.BREAK_PASS
      return e_context
    
    def query_task_result(self):
      task_ids = list(self.task_id_dict.keys())
      logger.info("[Midjourney] handle task , size [%s]", len(task_ids))
      if len(task_ids) == 0:
          return
      tasks = self.post_json('/task/list-by-condition', {'ids': task_ids})
      for task in tasks:
          task_id = task['id']
          description = task['description']
          status = task['status']
          action = task['action']

          if status == 'SUCCESS':
              logger.debug("[Midjourney] 任务已完成: " + task_id)
              self.task_id_dict.pop(task_id)
              if action == 'DESCRIBE' or action == 'SHORTEN':
                  prompt = task['properties']['finalPrompt']
                  reply = (reply_prefix + '✅ 任务已完成\n📨 任务ID: %s\n%s\n\n' + self.get_buttons(
                          task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                    task_id, prompt, task_id)
                  self.channel.send_text(reply, self.context_dict[task_id])
              elif action == 'UPSCALE':
                  reply = ('✅ 任务已完成\n📨 任务ID: %s\n✨ %s\n\n' + self.get_buttons(
                                    task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                    task_id, description, task_id)
                  # url_reply = Reply(ReplyType.IMAGE_URL, task['imageUrl'])
                  self.channel.send_text(reply, self.context_dict[task_id])
                  self.channel.send_image(task['imageUrl'], self.context_dict[task_id])
              else:
                  reply = ('✅ 任务已完成\n📨 任务ID: %s\n✨ %s\n\n' + self.get_buttons(
                                    task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                    task_id, description, task_id)
                  # image_storage = self.download_and_compress_image(task['imageUrl'])
                  self.channel.send_text(reply, self.context_dict[task_id])
                  self.channel.send_image(task['imageUrl'], self.context_dict[task_id])
          elif status == 'MODAL':
              res = self.post_json('/submit/modal', {'taskId': task_id})
              if res.get("code") != 1:
                  self.task_id_dict.pop(task_id)
                  reply = reply_prefix + '❌ 任务执行失败\n✨ %s\n📨 任务ID: %s\n📒 失败原因: %s' % (description, task_id, res.get("description"))
                  self.channel.send_text(reply, self.context_dict[task_id])
          elif status == 'FAILURE':
              self.task_id_dict.pop(task_id)
              reply = reply_prefix + '❌ 任务执行失败\n✨ %s\n📨 任务ID: %s\n📒 失败原因: %s' % (
                            description, task_id, task['failReason'])
              self.channel.send_text(reply, self.context_dict[task_id])
      
    def get_events(self):
      return self.handlers
    def get_task(self, task_id):
      return requests.get(url=self.proxy_server + '/task/%s/fetch' % task_id, headers={'mj-api-secret': self.proxy_api_secret}).json()
    def handle_shorten(self, prompt, state):
      return self.post_json('/submit/shorten', {'prompt': prompt, 'state': state})
    def post_json(self, api_path, data):
      return requests.post(url=self.proxy_server + api_path, json=data, headers={'mj-api-secret': ""}).json()
    def add_task(self, task_id):
      self.task_id_dict[task_id] = 'NOT_START'
    def add_context(self, task_id, context):
      self.context_dict[task_id] = context
    def get_buttons(self, task):
      res = ''
      index = 1
      for button in task['buttons']:
        name = button['emoji'] + button['label']
        if name in ['🎉Imagine all', '❤️']:
            continue
        res += ' %d- %s\n' % (index, name)
        index += 1
      return res

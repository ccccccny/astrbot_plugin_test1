from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from astrbot.api.message_components import *
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.quoted_message_parser import *

from pathlib import Path
import httpx

@register("edit", "img", "一个图像编辑插件", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        hash_dict = {}  # 后续实现去重图片，通过path.rglob递归搜索文件
        plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        plugin_images_path = plugin_data_path / "images"
        self.plugin_groups_path = plugin_images_path / "groups"
        self.plugin_friends_path = plugin_images_path / "friends"

        if not plugin_data_path.exists():
            plugin_data_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"插件数据目录不存在，已创建目录: {plugin_data_path}")
        if not plugin_images_path.exists():
            plugin_images_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"-图片目录不存在，已创建目录: {plugin_images_path}")
        if not self.plugin_groups_path.exists():
            self.plugin_groups_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"-图片群组目录不存在，已创建目录: {self.plugin_groups_path}")
        if not self.plugin_friends_path.exists():
            self.plugin_friends_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"-图片好友目录不存在，已创建目录: {self.plugin_friends_path}")



    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @filter.command("edit")
    async def edit_img(self, event: AstrMessageEvent):
        """这是一个图像编辑指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。

        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *

        logger.info(message_chain)

        image_urls = []

        for msg in message_chain:
            if msg.type == "Reply":
                image_urls = await extract_quoted_message_images(event, msg)  # 提取图片下载地址
                break
        if not image_urls:
            yield event.plain_result("❌ 未在引用消息中找到任何图片！")
        else:  # 发现图片，开始下载
            logger.info(f"✅ 引用里的图片 URLs: {image_urls}")
            # 初始化目录
            if event.is_private_chat():  # 私聊
                sender_id = event.get_sender_id()
                download_path = self.plugin_friends_path / f"{sender_id}"
            else:  # 群聊
                group_id = event.get_group_id()
                sender_id = event.get_sender_id()
                download_path = self.plugin_groups_path / f"{group_id}" / f"{sender_id}"

            if not download_path.exists():
                download_path.mkdir(parents=True, exist_ok=True)

            # 异步下载每张图片
            logger.info(f"[img编辑插件] 开始下载 {len(image_urls)} 张图片...")
            save_path = []
            for idx, url in enumerate(image_urls):
                files = [f for f in download_path.glob('*') if f.is_file() and not f.name.startswith('.')]
                len_files = len(files)
                await self.download_image_async(url, download_path / f"{str(len_files+1)}.jpg")
                save_path.append(download_path / f"{str(len_files+1)}.jpg")

            yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!已成功下载{len(image_urls)}张图片到 {download_path}") # 发送一条纯文本消息


    async def download_image_async(self, url: str, save_path: str | Path):
        """
        使用 httpx 异步下载图片
        :param url: 图片 URL
        :param save_path: 本地保存路径
        """
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, follow_redirects=True) as resp:
                resp.raise_for_status()  # 检查请求是否成功
                with open(save_path, "wb") as f:
                    # 流式写入，不占内存
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

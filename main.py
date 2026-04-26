from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from astrbot.api.message_components import *
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.quoted_message_parser import *

from pathlib import Path
import httpx
import base64

@register("edit", "img", "一个图像编辑插件", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        self.config = await self.context.load_plugin_config(self.name)
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

        # 提取用户输入的编辑提示词
        prompt = event.message_str.strip()
        if not prompt:
            yield event.plain_result("❌ 请提供编辑描述！\n用法：引用图片并发送 /edit 将背景换成森林")
            return

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
            save_paths = []
            for idx, url in enumerate(image_urls):
                files = [f for f in download_path.glob('*') if f.is_file() and not f.name.startswith('.')]
                len_files = len(files)
                await self.download_image_async(url, download_path / f"{str(len_files+1)}.jpg")
                save_paths.append(download_path / f"{str(len_files+1)}.jpg")

            # 发送"处理中"提示
            yield event.plain_result(f"🎨 正在使用 AI 编辑图片，请稍候... (提示词: {prompt})")
            # 调用 AI 图像编辑 API
            try:
                edited_images = await self.call_ai_image_edit_siliconflow(save_paths[0], prompt)
                
                # 6. 发送编辑后的图片
                if edited_images:
                    message_chain = []  # 创建富媒体消息
                    for img_url in edited_images:
                        message_chain.append(Image.fromURL(img_url))  # # 从 URL 发送图片
                    message_chain.append(At(qq=event.get_sender_id()))
                    message_chain.append(Plain(f"\n✅ 编辑完成！\n原始图片: {len(image_urls)} 张\n编辑指令: {prompt}"))
                    yield event.chain_result(message_chain)
                else:
                    yield event.plain_result("❌ AI 图片编辑失败，请检查配置或重试")
                    
            except Exception as e:
                logger.error(f"图片编辑失败: {e}")
                yield event.plain_result(f"❌ 编辑失败: {str(e)}")


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

    async def call_ai_image_edit_siliconflow(self, image_path: Path, prompt: str) -> list:
        """
        调用硅基流动 (SiliconFlow) 的 Qwen-Image-Edit API
        """
        # 从配置中读取 API 信息
        if not self.config:
            self.config = await self.context.load_plugin_config(self.name)
        
        api_key = self.config.get("siliconflow_api_key")
        model = self.config.get("edit_model", "Qwen/Qwen-Image-Edit-2509")
        
        if not api_key:
            raise Exception("❌ 未配置 SiliconFlow API Key，请在插件配置中填写")
        
        # 读取图片并转为 Base64
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode()
        
        # 硅基流动 API 地址（与 OpenAI 兼容）
        url = "https://api.siliconflow.cn/v1/images/generations"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建请求体
        data = {
            "model": model,
            "prompt": prompt,
            "image": f"data:image/jpeg;base64,{image_base64}",  # Qwen-Image-Edit 需要这个字段
            "image_size": "1328x1328",   # Qwen-Image 推荐尺寸
            "cfg_scale": 4.0,            # CFG 值，配合 50 步使用
            "num_inference_steps": 50,   # 推理步数，50 步效果最佳
            "seed": None                  # 可选，固定种子可复现结果
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:  # 图像编辑时间较长
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            # 提取生成的图片 URL
            image_urls = [item["url"] for item in result.get("images", [])]
            return image_urls


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

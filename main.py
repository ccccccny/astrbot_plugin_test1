from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from astrbot.api.message_components import *
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.quoted_message_parser import *
from astrbot.api import AstrBotConfig

from pathlib import Path
import httpx
import base64
import asyncio
import mimetypes
import os
import aiofiles
from PIL import Image
import io

@register("edit", "img", "一个图像编辑插件", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

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
    async def edit_img(self, event: AstrMessageEvent, prompt: str):
        """这是一个图像编辑指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。

        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *

        logger.info(message_chain)
        # logger.info(message_str)

        image_urls = []

        # 提取用户输入的编辑提示词
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
            data = []
            for idx, url in enumerate(image_urls):
                logger.info(f"正在处理第{idx+1}/{len(image_urls)}张图片")
                files = [f for f in download_path.glob('*') if f.is_file() and not f.name.startswith('.')]
                len_files = len(files)
                img_path = download_path / f"{len_files+1}.jpg"
                await self.download_image_async(url, img_path)
                logger.info(f"第{idx+1}/{len(image_urls)}张图片下载完成")
                save_paths.append(img_path)
                resized_data = await self.resize_img(img_path)
                logger.info(f"第{idx+1}/{len(image_urls)}张图片尺寸处理完成")
                async with aiofiles.open(img_path, 'wb') as f:
                    await f.write(resized_data)
                logger.info(f"第{idx+1}/{len(image_urls)}张图片已保存")
                img_data = await self.image_to_data_url(img_path)
                logger.info(f"第{idx+1}/{len(image_urls)}张图片已编码数据")
                data.append(img_data)


            # 发送"处理中"提示
            yield event.plain_result(f"🎨 正在使用 AI 编辑图片，请稍候... (提示词: {prompt})")
            # 调用 AI 图像编辑 API
            try:
                logger.info(f"开始调用modelscope API")
                logger.info(f"传入的 image_data 长度: {len(data)}")
                edited_images = await self.call_ai_image_edit_modelscope(data, prompt)
                
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
                
                async with aiofiles.open(save_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        await f.write(chunk)

    async def resize_img(self,image_path, max_width=1328, max_height=1328, quality=85):
        """
        将图片调整到指定尺寸以内，保持原比例
        
        Args:
            image_path: 图片路径
            max_width: 最大宽度（像素）
            max_height: 最大高度（像素）
            quality: JPEG压缩质量（1-100），仅对JPEG有效
        
        Returns:
            调整后的图片二进制数据
        """
        # 同步读取图片（PIL不支持异步）
        def resize_sync():
            with Image.open(image_path) as img:
                original_width, original_height = img.size
                
                # 计算缩放比例
                width_ratio = max_width / original_width
                height_ratio = max_height / original_height
                scale_ratio = min(width_ratio, height_ratio, 1.0)  # 只缩小不放大
                
                if scale_ratio < 1.0:
                    new_width = int(original_width * scale_ratio)
                    new_height = int(original_height * scale_ratio)
                    
                    # 使用高质量重采样算法
                    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                else:
                    img_resized = img
                
                # 保存到内存
                output = io.BytesIO()
                
                # 根据原图格式选择保存格式
                if img.format == 'PNG' and img.mode in ('RGBA', 'LA', 'P'):
                    img_resized.save(output, format='PNG', optimize=True)
                else:
                    # JPEG格式
                    if img_resized.mode in ('RGBA', 'LA', 'P'):
                        # 转换为RGB
                        rgb_img = Image.new('RGB', img_resized.size, (255, 255, 255))
                        rgb_img.paste(img_resized, mask=img_resized.split()[-1] if img_resized.mode == 'RGBA' else None)
                        img_resized = rgb_img
                    img_resized.save(output, format='JPEG', quality=quality, optimize=True)
                
                return output.getvalue()
        
        # 在线程池中执行同步操作
        return await asyncio.to_thread(resize_sync)

    async def image_to_data_url(self,image_path):
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        async with aiofiles.open(image_path, "rb") as f:  # 使用异步库
            image_data = await f.read()

        mime_type, _ = mimetypes.guess_type(image_path)

        if mime_type is None or not mime_type.startswith('image/'):
            mime_type = 'image/png'

        base64_encoded = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{base64_encoded}"

    async def call_ai_image_edit_modelscope(self, image_data: list, prompt: str) -> list:
        """
        调用魔搭 (ModelScope) 的 Qwen-Image-Edit API
        使用官方示例的 image_url 方式
        """
        api_key = self.config.get("api_key")
        model = self.config.get("edit_model", "Qwen/Qwen-Image-Edit-2511")  # 使用最新版
        
        if not api_key:
            raise Exception("❌ 未配置 ModelScope API Key，请在插件配置中填写")
        
        # 注意：需要将本地图片上传到某个可访问的 URL，或者使用方案2的 base64
        # 这里假设你的图片已经有可访问的 URL（从引用消息中获取）
        # 但你的代码中 save_paths[0] 是本地路径，需要转换
        
        # 临时方案：你需要先把图片上传到某个地方获取 URL
        # 或者使用方案2的 base64 方式
        
        # 魔搭 API 地址
        url = "https://api-inference.modelscope.cn/v1/images/generations"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        # 使用官方示例的格式
        data = {
            "model": model,
            "prompt": prompt,
            "image_url": image_data  # 这里需要传入图片的编码数据
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"发送请求到: {url}")
            # 1. 提交任务
            response = await client.post(url, headers=headers, json=data)
            logger.info(f"API 状态码: {response.status_code}")
            logger.info(f"API 原始响应: {response.text}")
            response.raise_for_status()
            task_id = response.json()["task_id"]
            
            # 2. 轮询任务状态
            while True:
                status_url = f"https://api-inference.modelscope.cn/v1/tasks/{task_id}"
                status_headers = {
                    "Authorization": f"Bearer {api_key}",
                    "X-ModelScope-Task-Type": "image_generation"
                }
                result = await client.get(status_url, headers=status_headers)
                result.raise_for_status()
                task_data = result.json()
                
                if task_data["task_status"] == "SUCCEED":
                    return task_data.get("output_images", [])
                elif task_data["task_status"] == "FAILED":
                    raise Exception(f"图像编辑失败: {task_data.get('message', '未知错误')}")
                
                await asyncio.sleep(5)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

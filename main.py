import os
import logging
from datetime import datetime
from typing import Optional

from llm import LLMInterface
from memory import MemoryManager


class ChatBot:
    """聊天机器人主程序"""

    def __init__(self, config_path: str = "config.txt"):
        """初始化聊天机器人

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.config = self._load_config(config_path)

        # 设置日志
        self._setup_logging()

        # 初始化组件
        self.memory = MemoryManager(config_path)
        self.llm = LLMInterface(config_path)

        # 加载或创建会话
        self._initialize_session()

    def _load_config(self, path: str) -> dict:
        """加载配置文件"""
        config = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
        return config

    def _setup_logging(self):
        """设置日志"""
        log_level = (
            logging.DEBUG
            if self.config["DEBUG_MODE"].lower() == "true"
            else logging.INFO
        )

        # 创建logs目录
        os.makedirs("logs", exist_ok=True)

        # 设置日志格式
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # 文件处理器
        file_handler = logging.FileHandler(
            f"logs/chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        # 配置根日志记录器
        logging.root.setLevel(log_level)
        logging.root.addHandler(file_handler)

        # 设置网络相关模块的日志级别为WARNING
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)

        self.logger = logging.getLogger("ChatBot")

    def _initialize_session(self):
        """初始化会话"""
        # 检查是否有未完成的会话
        results = self.memory.conv_table.search().to_list()
        if results:
            # 获取最新的会话ID
            latest_session = max(results, key=lambda x: x["timestamp"])
            self.memory.load_session(latest_session["session_id"])
            session_start = datetime.fromtimestamp(latest_session["timestamp"])
            self.logger.info(f"恢复会话,开始时间: {session_start}")

            # 记录最近的对话历史
            conversations = self.memory.get_current_conversation()
            max_conv_num = int(self.config["MAX_CONV_NUM"])
            if conversations:
                history = "\n=== 历史对话 ===\n"
                for conv in conversations[-max_conv_num:]:
                    history += f"\n{conv['role'].title()}: {conv['text']}"
                history += "\n==============="
                self.logger.info(history)
        else:
            # 开始新会话
            self.memory.start_new_session()
            self.logger.info(f"开始新会话,时间: {datetime.now()}")

    def _process_command(self, command: str) -> bool:
        """处理特殊命令

        Args:
            command: 用户输入的命令

        Returns:
            是否继续运行
        """
        if command == "/reset":
            self.logger.info("重置当前会话")
            self.memory.reset_session()
            print("会话已重置")
            return True
        elif command == "/save":
            self.logger.info("归档当前会话")
            self.memory.save_session()
            print("会话已归档,开始新会话")
            return True
        elif command == "/exit":
            self.logger.info("退出程序")
            print("再见!")
            return False
        return True

    def _format_debug_info(self, **kwargs) -> str:
        """格式化调试信息"""
        debug_info = "\n=== 调试信息 ===\n"
        for key, value in kwargs.items():
            debug_info += f"{key}:\n{value}\n\n"
        debug_info += "===============\n"
        return debug_info

    def chat_loop(self):
        """主对话循环"""
        print(f"会话开始时间: {datetime.now()}")
        print('输入"/reset"重置会话,"/save"归档会话,"/exit"退出程序')

        while True:
            # 获取用户输入
            user_input = input("\n用户: ").strip()
            if not user_input:
                continue

            # 处理特殊命令
            if user_input.startswith("/"):
                if not self._process_command(user_input):
                    break
                continue

            # 记录用户输入
            self.memory.save_conversation("User", user_input)

            try:
                # 检索相关记忆
                relevant_memories = self.memory.get_relevant_memories(
                    user_input, exclude_session_id=self.memory.current_session_id
                )

                # 获取当前对话
                current_conversation = self.memory.get_current_conversation()

                # 生成回复
                response = self.llm.chat(
                    user_input=user_input,
                    self_perception=self.memory.self_perception,
                    user_perception=self.memory.user_perception,
                    conversation_summary=self.memory.current_summary,
                    relevant_memories=relevant_memories,
                    current_conversation=current_conversation,
                )

                # 记录调试信息
                if self.config["DEBUG_MODE"].lower() == "true":
                    debug_info = self._format_debug_info(
                        自我认知=self.memory.self_perception,
                        用户形象=self.memory.user_perception,
                        当前会话总结=self.memory.current_summary or "暂无总结",
                        相关记忆=relevant_memories,
                        当前对话=current_conversation,
                    )
                    self.logger.debug(debug_info)

                # 保存助手回复
                self.memory.save_conversation("Assistant", response)

                # 更新对话总结
                self.memory.update_summary()

                # 输出回复
                print(f"\n助手: {response}")

            except Exception as e:
                self.logger.error(f"处理用户输入时出错: {str(e)}", exc_info=True)
                print("\n抱歉,处理您的输入时出现错误。请重试。")


def main():
    """程序入口"""
    try:
        bot = ChatBot()
        bot.chat_loop()
    except Exception as e:
        logging.error(f"程序运行时出错: {str(e)}", exc_info=True)
        print("\n程序遇到错误需要退出。请查看日志了解详情。")


if __name__ == "__main__":
    main()

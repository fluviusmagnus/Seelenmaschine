import json
import re
from pathlib import Path
from typing import Dict, Any


class PersonaMemoryConverter:
    def __init__(self, txt_content: str):
        self.content = txt_content
        self.data = {}

    def convert(self) -> Dict[str, Any]:
        bot: Dict[str, Any] = {
            "name": "Seelenmaschine",
            "gender": "neutral",
            "birthday": "2025-02-15",
            "role": "AI assistant",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {
                "description": "concise and helpful",
                "examples": []
            },
            "personality": {
                "mbti": "",
                "description": "",
                "worldview_and_values": ""
            },
            "emotions_and_needs": {
                "long_term": "",
                "short_term": ""
            },
            "relationship_with_user": ""
        }

        sections = self._parse_sections()
        
        if "【基础信息】" in sections:
            self._parse_basic_info(sections["【基础信息】"], bot)
        
        if "【性格观念】" in sections:
            self._parse_personality(sections["【性格观念】"], bot)
        
        if "【兴趣偏好】" in sections:
            self._parse_interests(sections["【兴趣偏好】"], bot)
        
        if "【语言风格】" in sections:
            self._parse_language_style(sections["【语言风格】"], bot)
        
        if "【心境状态】" in sections:
            self._parse_emotions(sections["【心境状态】"], bot)
        
        if "【关系认知】" in sections:
            self._parse_relationship(sections["【关系认知】"], bot)
        
        if "【重要事件】" in sections:
            self._parse_events(sections["【重要事件】"], bot)

        return bot

    def _parse_sections(self) -> Dict[str, str]:
        pattern = r'##\s*(【[^】]+】)'
        headers = list(re.finditer(pattern, self.content))
        sections = {}
        
        for i, match in enumerate(headers):
            section_name = match.group(1)
            start = match.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(self.content)
            sections[section_name] = self.content[start:end].strip()
        
        return sections

    def _parse_basic_info(self, text: str, bot: Dict[str, Any]):
        for line in text.split('\n'):
            line = line.strip()
            if '姓名' in line and ':' in line:
                bot["name"] = line.split(':', 1)[1].strip()
            elif '性别' in line and ':' in line:
                bot["gender"] = line.split(':', 1)[1].strip()
            elif '生日' in line and ':' in line:
                match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', line)
                if match:
                    bot["birthday"] = f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
            elif '身体特征' in line:
                rest = text[text.find(line):].split('\n', 1)[1] if '\n' in text[text.find(line):] else ''
                bot["appearance"] = rest.strip()

    def _parse_personality(self, text: str, bot: Dict[str, Any]):
        desc_parts = []
        worldview = []
        
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('-') and ':' in line:
                key = line.split(':', 1)[0].replace('-', '').strip()
                if 'MBTI' in key:
                    bot["personality"]["mbti"] = line.split(':', 1)[1].strip()
                elif '世界观' in key:
                    worldview.append(line.split(':', 1)[1].strip())
                elif '人生观' in key or '价值观' in key:
                    desc_parts.append(line.split(':', 1)[1].strip())
        
        bot["personality"]["description"] = '\n'.join(desc_parts)
        bot["personality"]["worldview_and_values"] = '\n'.join(worldview)

    def _parse_interests(self, text: str, bot: Dict[str, Any]):
        likes = []
        dislikes = []
        current_category = None
        
        for line in text.split('\n'):
            line = line.strip()
            if '喜好' in line or '爱好' in line or '偏好' in line:
                current_category = 'likes'
            elif '不喜欢' in line or '厌恶' in line:
                current_category = 'dislikes'
            elif line.startswith('-') and current_category:
                item = line.replace('-', '').strip()
                if current_category == 'likes':
                    likes.append(item)
                else:
                    dislikes.append(item)
        
        bot["likes"] = likes[:10]
        bot["dislikes"] = dislikes[:5]

    def _parse_language_style(self, text: str, bot: Dict[str, Any]):
        examples = []
        desc_lines = []
        in_example = False
        
        for line in text.split('\n'):
            line = line.strip()
            if '示例' in line:
                in_example = True
                examples.append(line.split(':', 1)[1].strip() if ':' in line else line)
            elif in_example and line:
                examples.append(line)
            elif line.startswith('-') and '模式' in line:
                desc_lines.append(line)
        
        bot["language_style"]["description"] = '\n'.join(desc_lines)
        bot["language_style"]["examples"] = examples[:5]

    def _parse_emotions(self, text: str, bot: Dict[str, Any]):
        long_term = []
        short_term = []
        
        for line in text.split('\n'):
            line = line.strip()
            if '长期情绪' in line and ':' in line:
                long_term.append(line.split(':', 1)[1].strip())
            elif '近期情绪' in line and ':' in line:
                short_term.append(line.split(':', 1)[1].strip())
            elif '长期需求' in line and ':' in line:
                long_term.append(line.split(':', 1)[1].strip())
            elif '近期需求' in line and ':' in line:
                short_term.append(line.split(':', 1)[1].strip())
        
        bot["emotions_and_needs"]["long_term"] = '\n'.join(long_term)
        bot["emotions_and_needs"]["short_term"] = '\n'.join(short_term)

    def _parse_relationship(self, text: str, bot: Dict[str, Any]):
        lines = text.split('\n')
        if lines:
            bot["relationship_with_user"] = '\n'.join([line.strip() for line in lines if line.strip()])

    def _parse_events(self, text: str, bot: Dict[str, Any]):
        pass


class UserProfileConverter:
    def __init__(self, txt_content: str):
        self.content = txt_content

    def convert(self) -> Dict[str, Any]:
        user: Dict[str, Any] = {
            "name": "",
            "gender": "",
            "birthday": "",
            "timezone": "Europe/Berlin",
            "personal_facts": [],
            "abilities": "",
            "likes": "",
            "dislikes": "",
            "personality": {
                "mbti": "",
                "description": "",
                "worldview_and_values": ""
            },
            "emotions_and_needs": {
                "long_term": "",
                "short_term": ""
            }
        }

        sections = self._parse_sections()
        
        if "【基础信息】" in sections:
            self._parse_basic_info(sections["【基础信息】"], user)
        
        if "【性格观念】" in sections:
            self._parse_personality(sections["【性格观念】"], user)
        
        if "【兴趣偏好】" in sections:
            self._parse_interests(sections["【兴趣偏好】"], user)
        
        if "【心境状态】" in sections:
            self._parse_emotions(sections["【心境状态】"], user)

        return user

    def _parse_sections(self) -> Dict[str, str]:
        pattern = r'##\s*(【[^】]+】)'
        headers = list(re.finditer(pattern, self.content))
        sections = {}
        
        for i, match in enumerate(headers):
            section_name = match.group(1)
            start = match.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(self.content)
            sections[section_name] = self.content[start:end].strip()
        
        return sections

    def _parse_basic_info(self, text: str, user: Dict[str, Any]):
        facts = []
        for line in text.split('\n'):
            line = line.strip()
            if '姓名' in line and ':' in line:
                user["name"] = line.split(':', 1)[1].strip()
            elif '性别' in line and ':' in line:
                user["gender"] = line.split(':', 1)[1].strip()
            elif '生日' in line and ':' in line:
                match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', line)
                if match:
                    user["birthday"] = f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
            elif line.startswith('-'):
                facts.append(line.replace('-', '').strip())
        
        user["personal_facts"] = facts[:10]

    def _parse_personality(self, text: str, user: Dict[str, Any]):
        desc_parts = []
        worldview = []
        
        for line in text.split('\n'):
            line = line.strip()
            if 'MBTI' in line and ':' in line:
                user["personality"]["mbti"] = line.split(':', 1)[1].strip()
            elif '世界观' in line and ':' in line:
                worldview.append(line.split(':', 1)[1].strip())
            elif line.startswith('-') and ':' in line:
                desc_parts.append(line.split(':', 1)[1].strip())
        
        user["personality"]["description"] = '\n'.join(desc_parts)
        user["personality"]["worldview_and_values"] = '\n'.join(worldview)

    def _parse_interests(self, text: str, user: Dict[str, Any]):
        likes = []
        dislikes = []
        
        for line in text.split('\n'):
            line = line.strip()
            if '喜好' in line or '喜好' in line:
                likes.append(line.split(':', 1)[1].strip() if ':' in line else line)
            elif '不喜欢' in line or '厌恶' in line:
                dislikes.append(line.split(':', 1)[1].strip() if ':' in line else line)
        
        user["likes"] = '\n'.join(likes[:5])
        user["dislikes"] = '\n'.join(dislikes[:3])

    def _parse_emotions(self, text: str, user: Dict[str, Any]):
        long_term = []
        short_term = []
        
        for line in text.split('\n'):
            line = line.strip()
            if '长期' in line and ':' in line:
                long_term.append(line.split(':', 1)[1].strip())
            elif '近期' in line and ':' in line:
                short_term.append(line.split(':', 1)[1].strip())
        
        user["emotions_and_needs"]["long_term"] = '\n'.join(long_term)
        user["emotions_and_needs"]["short_term"] = '\n'.join(short_term)


def convert_txt_to_json(persona_txt_path: str, user_txt_path: str, output_path: str) -> Dict[str, Any]:
    persona_content = Path(persona_txt_path).read_text(encoding='utf-8')
    user_content = Path(user_txt_path).read_text(encoding='utf-8')
    
    persona_converter = PersonaMemoryConverter(persona_content)
    user_converter = UserProfileConverter(user_content)
    
    bot_data = persona_converter.convert()
    user_data = user_converter.convert()
    
    result = {
        "bot": bot_data,
        "user": user_data,
        "memorable_events": [],
        "commands_and_agreements": []
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    
    return result

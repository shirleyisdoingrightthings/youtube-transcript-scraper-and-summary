import re

file_path = "output/Demis Hassabis｜AGI、Agent与下一个科学突破/Demis Hassabis｜AGI、Agent与下一个科学突破 - 逐字稿.md"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. 访谈信息格式
metadata_keys = ["视频标题", "主持人", "节目嘉宾", "视频链接", "播出时间", "逐字稿说明"]
for key in metadata_keys:
    content = content.replace(f"**{key}**: ", f"**{key}**：")

# 2. 核心观点格式
# Change from:
# **1. 标题**
# 正文
# To:
# 1. **标题**
#    正文
def fix_core_points(match):
    num = match.group(1)
    title = match.group(2)
    body = match.group(3)
    return f"{num}. **{title}**\n   {body}"

content = re.sub(r'\*\*(\d+)\.\s+([^\*]+)\*\*\n(.*)', fix_core_points, content)

# 3. (a) 逐字稿正文标题
content = content.replace("---\n\n**[00:00]", "---\n\n## 以下为逐字稿正文：\n\n**[00:00]")

# 3. (b) 逐字稿正文间距 (two spaces to one space after the colon in speaker name)
content = re.sub(r'(\*\*\[\d{2}:\d{2}\].*?：\*\*)\s+', r'\1 ', content)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

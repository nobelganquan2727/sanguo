import os
import json
import pymysql
import glob

def get_db_connection():
    return pymysql.connect(
        host=os.getenv('MYSQL_HOST', 'localhost'),
        user=os.getenv('MYSQL_USER', 'root'),
        password=os.getenv('MYSQL_PASSWORD', '123456'),
        database=os.getenv('MYSQL_DB', 'sanguo'),
        cursorclass=pymysql.cursors.DictCursor
    )

def apply_feedback():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 获取所有待处理的反馈
            cursor.execute("SELECT * FROM feedback WHERE status = 'pending'")
            feedbacks = cursor.fetchall()

            if not feedbacks:
                print("没有需要处理的反馈。")
                return

            # 加载所有 data/raw/ 的 JSON 文件
            raw_files = glob.glob('data/raw/*.json')
            
            for fb in feedbacks:
                event_id = fb['event_id']
                field_name = fb['field_name']
                proposed_value = fb['proposed_value']
                
                print(f"处理反馈 [ID:{fb['id']}] - 事件: {event_id}, 字段: {field_name}, 新值: {proposed_value}")

                found = False
                for filepath in raw_files:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        try:
                            events = json.load(f)
                        except:
                            continue
                    
                    file_modified = False
                    for idx, event in enumerate(events):
                        # 尝试通过 id 匹配，如果 raw 数据里没有 id，就用 event_title 匹配
                        match_id = event.get('id') == event_id if event.get('id') else False
                        match_title = event.get('事件标题') == fb['event_title'] or event.get('title') == fb['event_title']
                        
                        if match_id or match_title:
                            found = True
                            file_modified = True
                            
                            # 替换新值 (如果是 locations，用逗号分隔转数组)
                            if field_name == 'locations':
                                new_list = [v.strip() for v in proposed_value.split(',') if v.strip()]
                                if '地点' in event:
                                    event['地点'] = proposed_value  # 保持原始中文字符串或者按需存数组
                                if 'locations' in event:
                                    event['locations'] = new_list
                            elif field_name == 'std_start_year':
                                try:
                                    event['std_start_year'] = int(proposed_value)
                                    # 如果原始数据里有“时间”这一项，也把它更新成对应的字符串
                                    if '时间' in event:
                                        event['时间'] = f"{proposed_value}年"
                                except ValueError:
                                    # 如果不是纯数字，那就不强转 int
                                    event['std_start_year'] = proposed_value
                            else:
                                event[field_name] = proposed_value
                            
                            print(f"  -> 已在文件 {filepath} 中更新。")
                            break
                    
                    if file_modified:
                        # 写回文件
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(events, f, ensure_ascii=False, indent=2)
                        
                        # 在数据库中标记为已应用
                        cursor.execute("UPDATE feedback SET status = 'applied' WHERE id = %s", (fb['id'],))
                        conn.commit()
                        break
                
                if not found:
                    print(f"  -> 警告: 在 raw JSON 中未找到对应事件 ID '{event_id}'。")

    except Exception as e:
        print(f"执行出错: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    apply_feedback()

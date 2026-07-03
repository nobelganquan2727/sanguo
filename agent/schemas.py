from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Union

class IntentAnalysis(BaseModel):
    type: Literal["complex", "generic_chat"] = Field(
        description="意图分类：complex为历史问题查询，generic_chat为闲聊。"
    )
    rewritten_question: str = Field(
        description="消解代词与指代并重写后的独立完整提问。"
    )
    entities: List[str] = Field(
        description="重写后提问中包含的核心历史人物、官职或地点。"
    )
    historical_characters: List[str] = Field(
        default_factory=list,
        description="重写后提问中显式提到的具体历史人物姓名列表。"
    )


class SearchVectorGraphArgs(BaseModel):
    query: str = Field(description="通过自然语言描述进行语义向量检索，查找与查询最相关的历史事件和史料原文")
    k: Optional[Union[int, str]] = Field(default=5, description="检索结果条数")


class SearchHistoricalTextArgs(BaseModel):
    keyword: str = Field(description="通过精确关键字模糊搜索相关的历史事件描述和史料原文")


class GetPersonTimelineArgs(BaseModel):
    name: Union[str, List[str]] = Field(description="特定一个或多个三国历史人物的中文姓名，可以是一个中文名字符串，或者是包含多个中文名的列表，例如 '刘备' 或 ['曹操', '刘备']")
    start_year: Optional[Union[int, str]] = Field(default=None, description="起始年份，可选")
    end_year: Optional[Union[int, str]] = Field(default=None, description="结束年份，可选")
    query: Optional[str] = Field(default=None, description="（极重要）用于过滤生平的语义查询主题词。如果问题有明确的主题偏向（如'对内政策'、'战略调整'、'死因'、'推荐'），必须在此填入相关的现代或古代词汇进行语义过滤（如 '内政 法律 治理' 或 '战略 部署 军事'），严禁留空，以防拉取全量无用生平导致 Token 爆炸。")


class GetLocationTimelineArgs(BaseModel):
    location: Union[str, List[str]] = Field(description="特定一个或多个三国历史地名的中文名称，可以是一个中文名字符串，或者是包含多个中文名的列表，例如 '南海郡' 或 ['南海郡', '吴县']")
    start_year: Optional[Union[int, str]] = Field(default=None, description="起始年份，可选")
    end_year: Optional[Union[int, str]] = Field(default=None, description="结束年份，可选")
    query: Optional[str] = Field(default=None, description="（极重要）用于过滤地名时间轴的语义查询主题词。若有明确主题偏向，必须在此填入相关的语义过滤主题词，严禁留空。")


class QueryNeo4jArgs(BaseModel):
    question: Optional[str] = Field(default=None, description="针对三国图数据库的自然语言子问题或查询描述。")
    cypher: Optional[str] = Field(default=None, description="只读的 Neo4j Cypher 查询语句（仅用于兼容性/直接执行）。")


class TaskSpec(BaseModel):
    id: str = Field(description="任务的唯一标识，例如 task_1, task_2")
    tool: Literal[
        "search_vector_graph_async", 
        "get_person_timeline_async", 
        "get_location_timeline_async", 
        "query_neo4j_async", 
        "search_historical_text_async"
    ] = Field(description="要调用的原子检索工具名称")
    args: Union[
        SearchVectorGraphArgs,
        SearchHistoricalTextArgs,
        GetPersonTimelineArgs,
        GetLocationTimelineArgs,
        QueryNeo4jArgs
    ] = Field(description="工具的参数。如果要引用前置任务，参数值必须为 '{{task_id.output.属性}}' 占位符")
    dependencies: List[str] = Field(default=[], description="依赖的前置任务 ID 列表")


class DAGPlan(BaseModel):
    thought: str = Field(description="对用户问题进行拆解的思考与规划过程。")
    tasks: List[TaskSpec] = Field(default=[], description="拆解后的有向无环任务步骤列表")
    is_finished: bool = Field(default=False, description="标记目前收集到的史实数据是否已经足够回答用户的问题。如果足够，设为 true，此时 tasks 应为空。")


class TaskSpecNoNeo4j(BaseModel):
    id: str = Field(description="任务的唯一标识，例如 task_1, task_2")
    tool: Literal[
        "search_vector_graph_async", 
        "get_person_timeline_async", 
        "get_location_timeline_async", 
        "search_historical_text_async"
    ] = Field(description="要调用的原子检索工具名称")
    args: Union[
        SearchVectorGraphArgs,
        SearchHistoricalTextArgs,
        GetPersonTimelineArgs,
        GetLocationTimelineArgs
    ] = Field(description="工具的参数。如果要引用前置任务，参数值必须为 '{{task_id.output.属性}}' 占位符")
    dependencies: List[str] = Field(default=[], description="依赖的前置任务 ID 列表")


class DAGPlanNoNeo4j(BaseModel):
    thought: str = Field(description="对用户问题进行拆解的思考与规划过程。")
    tasks: List[TaskSpecNoNeo4j] = Field(default=[], description="拆解后的有向无环任务步骤列表")
    is_finished: bool = Field(default=False, description="标记目前收集到的史实数据是否已经足够回答用户的问题。如果足够，设为 true，此时 tasks 应为空。")

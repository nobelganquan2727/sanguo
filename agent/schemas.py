from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Union

class IntentAnalysis(BaseModel):
    type: Literal["complex", "generic_chat", "clarify"] = Field(
        description="意图类型。complex用于所有历史问题查询（包括特定单一史实、人物生平、人物关系、对比以及宏观/复杂的历史提问），将通过任务拆解进行查询；generic_chat用于日常问候与闲聊；clarify用于当用户问题中存在代词无法被消解、人名指代歧义、或缺少必要信息导致无法直接查询时，要求用户补充澄清。"
    )
    rewritten_question: str = Field(
        description="结合历史对话重写后的独立且完整的明确提问，若原句有代词或指代不清应消解代词并还原完整上下文。"
    )
    entities: List[str] = Field(
        description="问题中包含的核心历史人物、官职或地点。"
    )
    historical_characters: List[str] = Field(
        default_factory=list,
        description="重写后问题中显式提到的具体三国历史人物或虚构人物名字（例如：['曹操', '刘备']，或 ['哈利波特']）。如果没有具体人名，则为空列表。"
    )
    clarify_message: Optional[str] = Field(
        default=None,
        description="当type为clarify时，这里填写用来向用户进行澄清发问的中文话语，例如：'请问您指的是哪位刘备手下的将领？'。"
    )
    clarify_options: Optional[List[str]] = Field(
        default=None,
        description="当type为clarify时，为用户提供点击选择的澄清可选项列表（建议 2-4 个，如果没有明显的候选项则为空列表），例如：['刘备', '曹操']。"
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
    query: Optional[str] = Field(default=None, description="可选的语义过滤查询")


class QueryNeo4jArgs(BaseModel):
    question: Optional[str] = Field(default=None, description="针对三国图数据库的自然语言子问题或查询描述。")
    cypher: Optional[str] = Field(default=None, description="只读的 Neo4j Cypher 查询语句（仅用于兼容性/直接执行）。")


class TaskSpec(BaseModel):
    id: str = Field(description="任务的唯一标识，例如 task_1, task_2")
    tool: Literal[
        "search_vector_graph_async", 
        "get_person_timeline_async", 
        "query_neo4j_async", 
        "search_historical_text_async"
    ] = Field(description="要调用的原子检索工具名称")
    args: Union[
        SearchVectorGraphArgs,
        SearchHistoricalTextArgs,
        GetPersonTimelineArgs,
        QueryNeo4jArgs
    ] = Field(description="工具的参数。如果要引用前置任务，参数值必须为 '{{task_id.output.属性}}' 占位符")
    dependencies: List[str] = Field(default=[], description="依赖的前置任务 ID 列表")


class DAGPlan(BaseModel):
    thought: str = Field(description="对用户问题进行拆解的思考与规划过程。")
    tasks: List[TaskSpec] = Field(default=[], description="拆解后的有向无环任务步骤列表")

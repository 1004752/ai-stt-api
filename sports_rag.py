from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import UnstructuredFileLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings, CacheBackedEmbeddings
from langchain.vectorstores import Chroma
from langchain.storage import LocalFileStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

model = ChatOpenAI()
data_loaders = [
    UnstructuredFileLoader("./[홈팀]AT 마드리드_vs_[원정팀]도르트문트.txt"),
    UnstructuredFileLoader("./[홈팀]PSG_vs_[원정팀]바르셀로나.txt"),
    UnstructuredFileLoader("./[홈팀]레알 마드리드_vs_[원정팀]맨시티.txt"),
    UnstructuredFileLoader("./[홈팀]아스널_vs_[원정팀]바이에른 뮌헨.txt"),
]
cache_dir = LocalFileStore("./.cache/")


splitter = CharacterTextSplitter.from_tiktoken_encoder(
    separator="\n",
    chunk_size=500,
    chunk_overlap=50
)

docs = []
for loader in data_loaders:
    docs.extend(loader.load_and_split(text_splitter=splitter))
embeddings = OpenAIEmbeddings()
cached_embeddings = CacheBackedEmbeddings.from_bytes_store(embeddings, cache_dir)

vectorstore = Chroma.from_documents(docs, cached_embeddings)
retriever = vectorstore.as_retriever()

map_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
            질문에 답하기 위해 필요한 내용이 제시된 문장들 내에 포함되어 있는지 확인하세요. 만약 포함되어있다면, 요약본을 반환해주세요. 만약 관련된 내용이 없다면 다음 문장들을 그대로 반환해주세요 : ''
            -------
            {context}
            """,
        ),
        ("human", "{question}"),
    ]
)

map_chain = map_prompt | model

def map_docs(inputs):
    documents, question = inputs["documents"], inputs["question"]
    return "\n\n".join(
        map_chain.invoke({"context": doc.page_content, "question": question}).content
        for doc in documents
    )

map_results = {
                  "documents": retriever,
                  "question": RunnablePassthrough(),
              } | RunnableLambda(map_docs)

reduce_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
            주어진 문장들을 이용해 최종 답변을 작성해주세요. 만약 주어진 문장들 내에 답변을 위한 내용이 포함되어있지 않다면, 답변을 꾸며내지 말고, 모른다고 답해주세요.
            ------
            {context}
            """,
        ),
        ("human", "{question}"),
    ]
)

reduce_chain = {"context": map_results, "question": RunnablePassthrough()} | reduce_prompt | model

# reduce_chain.invoke("한국의 집단주의에 대해 설명해줘")

# 실시간 발언 예시 및 분석
commentary_examples = [
    "경기 시작 휘슬이 울렸습니다. 이제 경기가 시작되었네요.",
    "오늘 경기장의 날씨는 맑은 편입니다. 선수들에게 좋은 경기 환경이 될 것 같아요.",
    "골! 토트넘의 손흥민 선수가 왼발 슛으로 선제골을 넣었습니다!",
    "아스널 선수들이 패스를 주고받으며 공격을 전개하고 있습니다.",
    "후반전 추가 시간 3분이 주어졌습니다. 과연 승부는 어떻게 될까요?",
]

for commentary in commentary_examples:
    highlight = reduce_chain.invoke(commentary)
    if highlight:
        print(f"Highlight: {highlight}")
    else:
        print("No highlight extracted.")
    print()

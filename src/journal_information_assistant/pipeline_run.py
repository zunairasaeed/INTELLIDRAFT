# FastAPI app for Journal Information Assistant

from fastapi import FastAPI
from pydantic import BaseModel

from .publisher_mapping_engine.pipeline_run import run_pipeline

app = FastAPI(title="Journal Information Assistant API")


class PublisherMappingRequest(BaseModel):
    title: str
    abstract: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/publisher-mapping")
def publisher_mapping(req: PublisherMappingRequest):
    """Run publisher mapping pipeline: title + abstract → field + publisher recommendation."""
    return run_pipeline(title=req.title, abstract=req.abstract)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.journal_information_assistant.pipeline_run:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
    )

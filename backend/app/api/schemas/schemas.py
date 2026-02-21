import datetime

from pydantic import BaseModel


# --- Project ---
class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    template_id: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    template_id: str | None = None
    latex_content: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    template_id: str
    latex_content: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class ProjectList(BaseModel):
    projects: list[ProjectResponse]
    total: int


# --- Document ---
class DocumentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    original_name: str
    file_type: str
    parsed_content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


# --- Template ---
class TemplateVariable(BaseModel):
    type: str
    description: str


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    variables: dict[str, TemplateVariable]
    preview: str = ""
    is_builtin: bool = False


# --- Generation ---
class GenerateRequest(BaseModel):
    template_id: str = ""
    document_ids: list[str] = []


# --- Chat ---
class ChatRequest(BaseModel):
    message: str


class ChatMessageResponse(BaseModel):
    id: str
    project_id: str
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


# --- Edit Selection ---
class EditSelectionRequest(BaseModel):
    full_latex: str
    selected_text: str
    instruction: str
    selection_start: int
    selection_end: int


# --- Template Generation ---
class TemplateGenerateRequest(BaseModel):
    description: str


# --- Compile ---
class CompileRequest(BaseModel):
    latex_content: str | None = None


class CompileResponse(BaseModel):
    success: bool
    pdf_url: str = ""
    log: str = ""
    errors: list[str] = []


# --- LLM Config ---
class LLMConfigResponse(BaseModel):
    api_key_masked: str
    base_url: str
    model: str
    updated_at: str | None = None


class LLMConfigUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None

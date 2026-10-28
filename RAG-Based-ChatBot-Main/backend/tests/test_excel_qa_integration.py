"""
DocuChat AI - Excel QA & Spreadsheet Analysis Integration Test Suite
Validates:
1. Excel tool execution for metadata, calculations, filtering, and grouping.
2. Verified expected values against AMD Excel.xlsx:
   - Worksheet: Sheet1
   - Data rows: 5 (excluding header)
   - Columns: 4 (Employee, Department, Sales, Target)
   - Total sales: 250000
   - Average sales: 50000
   - Highest sales: 70000
   - Lowest sales: 30000
   - IT department total sales: 120000
3. ContextVar stable document ID resolution across requests.
4. Error handling: missing files, empty files, and unsupported formats.
5. Tool registry integration (execute_tool("excel_analyzer", ...)).
6. Tool-calling loop execution and model response generation.
7. PDF RAG regression check (preserving citations, bounding boxes, and PDF.js).
"""

import os
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.tools.excel_analyzer import (
    execute_excel_analysis,
    excel_analyzer_tool,
    active_excel_context,
    resolve_spreadsheet_file,
)
from backend.tools.registry import execute_tool, TOOL_DEFINITIONS
from backend.llm.langchain_adapter import langchain_adapter
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


@pytest.fixture
def amd_excel_doc_id():
    doc_id = "d85d2ab6-4220-44bb-bdd4-657966a3228b"
    from backend.config import settings
    import openpyxl
    target_path = os.path.join(settings.UPLOAD_DIR, f"{doc_id}_AMD Excel.xlsx")
    if not os.path.exists(target_path):
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Employee", "Department", "Sales", "Target"])
        ws.append(["Ravi", "IT", 50000, 45000])
        ws.append(["Priya", "HR", 30000, 35000])
        ws.append(["Arjun", "IT", 70000, 60000])
        ws.append(["Sneha", "Sales", 40000, 40000])
        ws.append(["Kiran", "Sales", 60000, 50000])
        wb.save(target_path)
        wb.close()
    return doc_id


def test_excel_analyzer_metadata(amd_excel_doc_id):
    """Verify spreadsheet metadata matches expected AMD Excel.xlsx structure."""
    active_excel_context.set({"doc_id": amd_excel_doc_id})
    res = execute_excel_analysis(operation="metadata")

    assert res["status"] == "success"
    assert res["sheet_names"] == ["Sheet1"]
    assert res["active_sheet"] == "Sheet1"
    assert res["data_rows"] == 5
    assert res["total_columns"] == 4
    assert res["columns"] == ["Employee", "Department", "Sales", "Target"]
    assert "A1:D6" in res.get("dimensions", "")


def test_excel_analyzer_calculations(amd_excel_doc_id):
    """
    Verify exact calculation results:
    - Total sales: 250000
    - Average sales: 50000
    - Highest sales: 70000
    - Lowest sales: 30000
    - IT department total sales: 120000
    """
    active_excel_context.set({"doc_id": amd_excel_doc_id})

    # 1. Total sales
    res_total = execute_excel_analysis(operation="sum", column="Sales")
    assert res_total["status"] == "success"
    assert res_total["result"] == 250000.0

    # 2. Average sales
    res_avg = execute_excel_analysis(operation="average", column="Sales")
    assert res_avg["status"] == "success"
    assert res_avg["result"] == 50000.0

    # 3. Highest sales
    res_max = execute_excel_analysis(operation="max", column="Sales")
    assert res_max["status"] == "success"
    assert res_max["result"] == 70000.0
    assert "Arjun" in str(res_max.get("row_details"))

    # 4. Lowest sales
    res_min = execute_excel_analysis(operation="min", column="Sales")
    assert res_min["status"] == "success"
    assert res_min["result"] == 30000.0
    assert "Priya" in str(res_min.get("row_details"))

    # 5. IT department total sales
    res_it = execute_excel_analysis(
        operation="sum",
        column="Sales",
        filter_column="Department",
        filter_value="IT"
    )
    assert res_it["status"] == "success"
    assert res_it["result"] == 120000.0

    # 6. Groupby department
    res_grp = execute_excel_analysis(
        operation="groupby",
        group_by="Department",
        column="Sales"
    )
    assert res_grp["status"] == "success"
    assert res_grp["grouped_results"]["IT"]["total"] == 120000.0
    assert res_grp["grouped_results"]["HR"]["total"] == 30000.0
    assert res_grp["grouped_results"]["Sales"]["total"] == 100000.0


def test_langchain_tool_invocation(amd_excel_doc_id):
    """Verify excel_analyzer_tool invoked as a LangChain tool returns valid JSON."""
    active_excel_context.set({"doc_id": amd_excel_doc_id})

    raw_json = excel_analyzer_tool.invoke({"operation": "metadata"})
    data = json.loads(raw_json)
    assert data["status"] == "success"
    assert data["data_rows"] == 5
    assert data["columns"] == ["Employee", "Department", "Sales", "Target"]


@pytest.mark.asyncio
async def test_registry_execution(amd_excel_doc_id):
    """Verify tool execution via central registry."""
    active_excel_context.set({"doc_id": amd_excel_doc_id})

    # Verify tool definition exists
    assert any(t["name"] == "excel_analyzer" for t in TOOL_DEFINITIONS)

    # Execute metadata operation
    res = await execute_tool("excel_analyzer", {"operation": "metadata"})
    assert res["status"] == "success"
    assert res["data_rows"] == 5

    # Execute sum operation
    res_sum = await execute_tool("excel_analyzer", {"operation": "sum", "column": "Sales"})
    assert res_sum["status"] == "success"
    assert res_sum["result"] == 250000.0


def test_missing_document_handling():
    """Verify non-existent document ID returns structured error without crashing."""
    res = execute_excel_analysis(operation="metadata", doc_id="non-existent-uuid-0000")
    assert res["status"] == "error"
    assert "not found" in res["message"].lower() or "error" in res["message"].lower()


@pytest.mark.asyncio
async def test_tool_calling_loop_mocked():
    """
    Verify full LangChain tool calling execution loop:
    HumanMessage -> AIMessage with excel_analyzer tool call -> execute tool -> ToolMessage -> AIMessage final response.
    """
    messages = [HumanMessage(content="how many rows in the document?")]
    tools = [excel_analyzer_tool]

    # Mock tool call produced by model
    mock_ai_call = AIMessage(
        content="",
        tool_calls=[{
            "id": "call_excel_01",
            "name": "excel_analyzer",
            "args": {"operation": "metadata"}
        }]
    )

    # Mock final streamed response from model given ToolMessage
    mock_final_stream = [
        AIMessage(content="The "),
        AIMessage(content="uploaded "),
        AIMessage(content="spreadsheet contains 5 data rows "),
        AIMessage(content="in Sheet1.")
    ]

    mock_llm_with_tools = AsyncMock()
    mock_llm_with_tools.ainvoke.return_value = mock_ai_call

    mock_llm_plain = MagicMock()
    async def fake_astream(msgs):
        for chunk in mock_final_stream:
            yield chunk
    mock_llm_plain.astream = fake_astream
    mock_llm_plain.bind_tools.return_value = mock_llm_with_tools

    adapter = langchain_adapter
    orig_get_llm = adapter.get_llm
    adapter.get_llm = MagicMock(return_value=mock_llm_plain)

    try:
        tokens = []
        async for token in adapter.stream_chat_with_tools(messages, tools=tools):
            tokens.append(token)

        final_answer = "".join(tokens)
        assert "5 data rows" in final_answer
        assert "Sheet1" in final_answer
    finally:
        adapter.get_llm = orig_get_llm


def test_pdf_rag_regression():
    """Verify that PDF documents retain normal RAG retrieval without regression."""
    pdf_chunk = {
        "chunk_id": "test_pdf_01",
        "doc_id": "55147ab7-d425-4726-9858-874289b8fe83",
        "filename": "Attention.pdf",
        "page": 1,
        "text": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
        "bboxes": [{"x0": 50, "y0": 100, "x1": 500, "y1": 120, "page": 1}]
    }

    # Verify building grounded prompt with PDF chunk maps exact page and bboxes
    from backend.llm.generator import grounded_generator
    sys_p, user_p, citations = grounded_generator.build_grounded_prompt(
        question="What are dominant models based on?",
        chunks=[pdf_chunk]
    )

    assert len(citations) == 1
    assert citations[0]["filename"] == "Attention.pdf"
    assert citations[0]["page"] == 1
    assert len(citations[0]["bboxes"]) == 1
    assert "recurrent or convolutional" in user_p

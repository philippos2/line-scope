"""Composition root for API services; constructing it performs no database work."""

from dataclasses import dataclass

from .agent.agent_input import ConversationStore
from .agent.read_agent import ReadAgent
from .application.agent_service import AgentApplication
from .application.approvals import HumanApproval
from .application.equipment_command import EquipmentCommandPrepare
from .application.execute import HumanExecute
from .application.maintenance_command import MaintenanceCommandPrepare
from .application.production_command import ProductionCommandPrepare
from .application.proposals import ProposalStore
from .application.reads import ReadTools
from .application.tools import ToolDispatcher
from .integrations.llm import OllamaClient
from .logging import EventLogger
from .persistence.database import Database
from .settings import Settings


@dataclass(frozen=True)
class ApiServices:
    settings: Settings
    database: Database
    events: EventLogger
    conversations: ConversationStore
    reads: ReadTools
    proposals: ProposalStore
    approval: HumanApproval
    execute: HumanExecute
    agent: AgentApplication


def build_api_services(
    settings=None, database=None, event_logger=None, *, llm=None, conversations=None
):
    settings = settings or Settings.env()
    database = database or Database(settings)
    events = event_logger or EventLogger(settings.log_level)
    conversations = conversations or ConversationStore()
    if llm is None and settings.llm_model:
        llm = OllamaClient(base_url=settings.llm_base_url, model=settings.llm_model)
    proposals = ProposalStore(database)
    read_agent = (
        ReadAgent(ToolDispatcher(database), llm, event_logger=events) if llm is not None else None
    )
    agent = AgentApplication(
        proposals=proposals,
        conversations=conversations,
        equipment=EquipmentCommandPrepare(database, event_logger=events),
        maintenance=MaintenanceCommandPrepare(database, event_logger=events),
        production=ProductionCommandPrepare(database, event_logger=events),
        read_agent=read_agent,
    )
    return ApiServices(
        settings=settings,
        database=database,
        events=events,
        conversations=conversations,
        reads=ReadTools(database),
        proposals=proposals,
        approval=HumanApproval(database, event_logger=events),
        execute=HumanExecute(database, settings, event_logger=events),
        agent=agent,
    )

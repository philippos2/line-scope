"""Composition root for API services; constructing it performs no database work."""

from dataclasses import dataclass

from neo4j import GraphDatabase

from .agent.agent_input import ConversationStore
from .agent.read_agent import ReadAgent
from .application.agent_service import AgentApplication
from .application.approvals import HumanApproval
from .application.capacity import CapacityInputs
from .application.dependency_command import DependencyCommandPrepare
from .application.economics import EconomicInputs
from .application.equipment_command import EquipmentCommandPrepare
from .application.execute import HumanExecute
from .application.graph_analysis import GraphAnalysis
from .application.graph_request import GraphLimits
from .application.knowledge_content import VerifiedKnowledgeContent
from .application.knowledge_flow import KnowledgeRetrieval
from .application.knowledge_metadata import KnowledgeMetadataGuard
from .application.maintenance_command import MaintenanceCommandPrepare
from .application.maintenance_inputs import MaintenanceInputs
from .application.production_command import ProductionCommandPrepare
from .application.proposals import ProposalStore
from .application.reads import ReadTools
from .application.registered_decision import RegisteredDecisions
from .application.safety import SafetyInputs
from .application.structured_command import StructuredCommandPrepare
from .application.tools import ToolDispatcher
from .graph.analysis_budget import GraphAnalysisBudget
from .graph.analysis_reader import GraphAnalysisReader
from .graph.analysis_states import GraphStateReader
from .integrations.knowledge_factory import knowledge_adapters
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
    capacity: CapacityInputs
    maintenance_inputs: MaintenanceInputs
    safety: SafetyInputs
    economics: EconomicInputs
    decisions: RegisteredDecisions
    agent: AgentApplication
    owned_graph_driver: object | None = None

    def close(self):
        if self.owned_graph_driver is not None:
            self.owned_graph_driver.close()


def build_api_services(
    settings=None,
    database=None,
    event_logger=None,
    *,
    llm=None,
    conversations=None,
    graph_driver=None,
):
    settings = settings or Settings.env()
    database = database or Database(settings)
    events = event_logger or EventLogger(settings.log_level)
    conversations = conversations or ConversationStore()
    if llm is None and settings.llm_model:
        llm = OllamaClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            context_tokens=settings.llm_context_tokens,
        )
    owned_driver = None
    if settings.neo4j_uri is not None and graph_driver is None:
        owned_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=settings.connect_seconds,
            connection_acquisition_timeout=settings.graph_timeout_ms / 1000,
            max_transaction_retry_time=0,
        )
        graph_driver = owned_driver
    try:
        graph = None
        if graph_driver is not None:
            graph = GraphAnalysis(
                GraphAnalysisReader(
                    database,
                    graph_driver,
                    graph_database=settings.neo4j_database,
                    timeout_seconds=settings.graph_timeout_ms / 1000,
                ),
                GraphStateReader(database),
                system_limits=GraphLimits(
                    settings.graph_max_depth,
                    settings.graph_max_nodes,
                    settings.graph_max_paths,
                    settings.graph_timeout_ms,
                ),
                budget_factory=GraphAnalysisBudget,
            )
        knowledge = None
        adapters = knowledge_adapters(settings)
        if adapters is not None:
            files, index = adapters
            knowledge = KnowledgeRetrieval(
                VerifiedKnowledgeContent(KnowledgeMetadataGuard(database), files),
                index,
            )
        proposals = ProposalStore(database)
        read_agent = (
            ReadAgent(
                ToolDispatcher(database, graph=graph, knowledge=knowledge),
                llm,
                event_logger=events,
                deadline_seconds=settings.read_agent_deadline_seconds,
            )
            if llm is not None
            else None
        )
        agent = AgentApplication(
            structured=StructuredCommandPrepare(database, event_logger=events),
            proposals=proposals,
            knowledge=knowledge,
            conversations=conversations,
            equipment=EquipmentCommandPrepare(database, event_logger=events),
            maintenance=MaintenanceCommandPrepare(database, event_logger=events),
            production=ProductionCommandPrepare(database, event_logger=events),
            dependency=DependencyCommandPrepare(database, event_logger=events),
            read_agent=read_agent,
            decision_flow=RegisteredDecisions(database, graph, knowledge),
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
            economics=EconomicInputs(database),
            maintenance_inputs=MaintenanceInputs(database),
            safety=SafetyInputs(database),
            capacity=CapacityInputs(database),
            decisions=RegisteredDecisions(database, graph, knowledge),
            agent=agent,
            owned_graph_driver=owned_driver,
        )
    except BaseException:
        if owned_driver is not None:
            owned_driver.close()
        raise

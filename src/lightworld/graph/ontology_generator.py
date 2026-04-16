
import json
from typing import Dict, Any, List, Optional
from lightworld.infrastructure.llm_client import LLMClient
from lightworld.infrastructure.llm_client_factory import LLMClientFactory


ONTOLOGY_SYSTEM_PROMPT = """You are an expert knowledge graph ontology designer. Your task is to analyze the given text content and simulation requirements, and design entity types and relationship types suitable for **social media opinion simulation**.

**IMPORTANT: You must output valid JSON data only. Do not output anything else.**

## Core Task Background

We are building a **social media opinion simulation system**. In this system:
- Each entity is an "account" or "agent" that can speak, interact, and spread information on social media
- Entities influence each other through reposts, comments, and responses
- We need to simulate how different parties react and how information propagates during public opinion events

Therefore, **entities must be real-world agents that can speak and interact on social media**:

**Acceptable**:
- Specific individuals (public figures, parties involved, opinion leaders, experts, ordinary people)
- Companies and enterprises (including their official accounts)
- Organizations (universities, associations, NGOs, unions, etc.)
- Government departments and regulatory agencies
- Media organizations (newspapers, TV stations, self-media, websites)
- Social media platforms themselves
- Representatives of specific groups (e.g., alumni associations, fan groups, advocacy groups)

**Not acceptable**:
- Abstract concepts (e.g., "public opinion", "sentiment", "trend")
- Topics/themes (e.g., "academic integrity", "education reform")
- Viewpoints/attitudes (e.g., "supporters", "opponents")

## Output Format

Please output JSON with the following structure:

```json
{
    "entity_types": [
        {
            "name": "EntityTypeName (English, PascalCase)",
            "description": "Brief description (English, max 100 chars)",
            "attributes": [
                {
                    "name": "attribute_name (English, snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["Example entity 1", "Example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "RELATION_TYPE_NAME (English, UPPER_SNAKE_CASE)",
            "description": "Brief description (English, max 100 chars)",
            "source_targets": [
                {"source": "SourceEntityType", "target": "TargetEntityType"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis of the text content"
}
```

## Design Guidelines (Extremely Important!)

### 1. Entity Type Design - Must Be Strictly Followed

**Quantity requirement: Exactly 10 entity types**

**Hierarchy requirements (must include both specific and fallback types)**:

Your 10 entity types must include the following hierarchy:

A. **Fallback types (required, placed as the last 2 in the list)**:
   - `Person`: Fallback type for any individual. Used when a person does not fit any more specific person type.
   - `Organization`: Fallback type for any organization. Used when an organization does not fit any more specific organization type.

B. **Specific types (8, designed based on text content)**:
   - Design more specific types for the main roles appearing in the text
   - E.g., for academic events: `Student`, `Professor`, `University`
   - E.g., for business events: `Company`, `CEO`, `Employee`

**Why fallback types are needed**:
- Various people appear in text, such as "elementary school teacher", "bystander", "anonymous netizen"
- If no specific type matches, they should be classified as `Person`
- Similarly, small organizations, temporary groups, etc. should be classified as `Organization`

**Design principles for specific types**:
- Identify high-frequency or key role types from the text
- Each specific type should have clear boundaries to avoid overlap
- Description must clearly explain how this type differs from the fallback type

### 2. Relationship Type Design

- Quantity: 6-10
- Relationships should reflect real connections in social media interactions
- Ensure source_targets cover the entity types you defined

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: Attribute names cannot use `name`, `uuid`, `group_id`, `created_at`, `summary` (these are reserved)
- Recommended: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity Type Reference

**Individual (Specific)**:
- Student
- Professor
- Journalist
- Celebrity
- Executive
- Official
- Lawyer
- Doctor

**Individual (Fallback)**:
- Person: Any individual (used when not fitting the above specific types)

**Organization (Specific)**:
- University
- Company
- GovernmentAgency
- MediaOutlet
- Hospital
- School
- NGO

**Organization (Fallback)**:
- Organization: Any organization (used when not fitting the above specific types)

## Relationship Type Reference

- WORKS_FOR
- STUDIES_AT
- AFFILIATED_WITH
- REPRESENTS
- REGULATES
- REPORTS_ON
- COMMENTS_ON
- RESPONDS_TO
- SUPPORTS
- OPPOSES
- COLLABORATES_WITH
- COMPETES_WITH
"""


class OntologyGenerator:

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClientFactory.get_shared_client()

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:

        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context
        )

        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]


        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )


        result = self._validate_and_process(result)

        return result


    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:


        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)


        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(Original text: {original_length} chars, truncated to first {self.MAX_TEXT_LENGTH_FOR_LLM} chars for ontology analysis)..."

        message = f"""## Simulation Requirement

{simulation_requirement}

## Document Content

{combined_text}
"""

        if additional_context:
            message += f"""
## Additional Notes

{additional_context}
"""

        message += """
Based on the above content, design entity types and relationship types suitable for social opinion simulation.

**Mandatory rules**:
1. Output exactly 10 entity types
2. The last 2 must be fallback types: Person (individual fallback) and Organization (organization fallback)
3. The first 8 are specific types designed based on text content
4. All entity types must be real-world agents that can speak, not abstract concepts
5. Attribute names must not use reserved words like name, uuid, group_id; use full_name, org_name, etc. instead
"""

        return message

    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:


        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""


        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []

            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."


        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."


        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10


        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }

        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }


        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names


        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)


            if current_count + needed_slots > MAX_ENTITY_TYPES:

                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES

                result["entity_types"] = result["entity_types"][:-to_remove]


            result["entity_types"].extend(fallbacks_to_add)


        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]

        return result

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MicroWorld for social opinion simulation',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== Entity Type Definitions ==============',
            '',
        ]


        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")

            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')

        code_lines.append('# ============== Relationship Type Definitions ==============')
        code_lines.append('')


        for edge in ontology.get("edge_types", []):
            name = edge["name"]

            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")

            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')

            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')

            code_lines.append('')
            code_lines.append('')


        code_lines.append('# ============== Type Configuration ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')


        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')

        return '\n'.join(code_lines)

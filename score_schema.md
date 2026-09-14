```
{
  "type": "object",
  "properties": {
    "Novelty_score": {"type": "number", "minimum": 1, "maximum": 10},
    "Novelty_reason": {"type": "string"},
    "Usefulness_score": {"type": "number", "minimum": 1, "maximum": 10},
    "Usefulness_reason": {"type": "string"},
    "Feasibility_score": {"type": "number", "minimum": 1, "maximum": 10},
    "Feasibility_reason": {"type": "string"},
    "Scalability_score": {"type": "number", "minimum": 1, "maximum": 10},
    "Scalability_reason": {"type": "string"},
    "Sustainability_score": {"type": "number", "minimum": 1, "maximum": 10},
    "Sustainability_reason": {"type": "string"},
    "Idea_Feedback": {"type": "string"}
  },
  "required": [
    "Novelty_score",
    "Novelty_reason",
    "Usefulness_score",
    "Usefulness_reason",
    "Feasibility_score",
    "Feasibility_reason",
    "Scalability_score",
    "Scalability_reason",
    "Sustainability_score",
    "Sustainability_reason",
    "Idea_Feedback"
  ],
  "additionalProperties": false
}
```
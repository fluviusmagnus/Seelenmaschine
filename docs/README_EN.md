# Seelenmaschine Documentation Directory

[中文](README.md)

This directory contains detailed feature documentation and usage guides for the Seelenmaschine project.

## 📚 Document List

### Feature Documentation

- **[SCHEDULED_TASKS_EN.md](SCHEDULED_TASKS_EN.md)** - Scheduled Task System
  - One-time and periodic tasks
  - Scheduled task tool usage guide
  - API reference and examples

- **[SEARCH_EXAMPLES.md](SEARCH_EXAMPLES.md)** - Memory Search Feature
  - FTS5 full-text search syntax
  - Boolean operator usage examples
  - Time and role filtering
  - Complex query examples

- **[MESSAGE_TYPES_AND_RETRIEVAL.md](MESSAGE_TYPES_AND_RETRIEVAL.md)** - Message Types and Retrieval Behavior
  - Message type catalog
  - Retrieval entry points and result shapes
  - Text catalog conventions

### Architecture / Refactor Documentation

- **[REDUNDANCY_REFACTOR_PLAN.md](REDUNDANCY_REFACTOR_PLAN.md)** - Current authoritative redundancy refactor progress ledger
  - Completed phases and retained components
  - Latest verification status
  - Rules for follow-up work

- **[ARCHITECTURE_REFACTOR_PLAN.md](ARCHITECTURE_REFACTOR_PLAN.md)** - Historical architecture refactor plan
  - Ownership goals for core / adapter / memory
  - Early phase breakdown
  - Current status is tracked in `REDUNDANCY_REFACTOR_PLAN.md`

- **[MEMORY_SEARCH_PLAN.md](MEMORY_SEARCH_PLAN.md)** - Historical memory search upgrade plan
  - Retrieval goals and migration plan
  - Test plan
  - Complements `SEARCH_EXAMPLES.md`

- **[TEXT_CATALOG_PLAN.md](TEXT_CATALOG_PLAN.md)** - Text Catalog refactor plan
  - Text identity and catalog direction
  - Complements the message retrieval document

## 🔗 Other Important Documents

These documents are located in the project root or adjacent directories:

- **[../README_EN.md](../README_EN.md)** - Main project documentation
  - Quick start
  - Configuration guide
  - Project structure
  - Usage instructions

- **[../migration/README_EN.md](../migration/README_EN.md)** - Migration tool technical documentation
  - Migration tool architecture
  - Developer guide
  - Testing instructions

- **[../AGENTS.md](../AGENTS.md)** - AI-assisted development guide
  - Code style guidelines
  - Build and test commands
  - Development workflow

## 📖 Browse by Topic

### Getting Started

1. Read [README_EN.md](../README_EN.md) to understand the project overview
2. Follow the quick start section to install and configure
3. If you have old data, refer to [migration/README_EN.md](../migration/README_EN.md)

### Feature Usage

- **Memory Search**: [SEARCH_EXAMPLES.md](SEARCH_EXAMPLES.md)
- **Message Types and Retrieval**: [MESSAGE_TYPES_AND_RETRIEVAL.md](MESSAGE_TYPES_AND_RETRIEVAL.md)
- **Scheduled Tasks**: [SCHEDULED_TASKS_EN.md](SCHEDULED_TASKS_EN.md)
- **Session Management**: See "Usage Instructions" section in [README_EN.md](../README_EN.md)

### Development Related

- **AI Development**: [AGENTS.md](../AGENTS.md)
- **Data Migration**: [migration/README_EN.md](../migration/README_EN.md)
- **Core runtime reference**: see the project structure section in [README_EN.md](../README_EN.md)
- **Refactor progress ledger**: [REDUNDANCY_REFACTOR_PLAN.md](REDUNDANCY_REFACTOR_PLAN.md)
- **Historical architecture plan**: [ARCHITECTURE_REFACTOR_PLAN.md](ARCHITECTURE_REFACTOR_PLAN.md)

## 🔄 Documentation Updates

Documentation is updated along with the project. If you find issues or need additional content, please submit an Issue or Pull Request.

## 📝 Contribution Guidelines

When improving documentation, please follow these principles:

1. **Clear and Concise** - Use simple and clear language
2. **Code Examples** - Provide practical code examples
3. **Keep in Sync** - Ensure documentation is consistent with code
4. **Bilingual** - Mainly use English, keep key terms in both languages

## 📞 Getting Help

- Check the project overview and runtime instructions in [README_EN.md](../README_EN.md)
- Check detailed documentation for relevant features
- Submit an Issue describing your problem

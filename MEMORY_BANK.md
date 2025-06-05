# Memory Bank

## Introduction
This file serves as a memory bank for the project. It is automatically updated to track code changes and explain the project's idea. The memory bank is designed to provide a comprehensive overview of the project's structure, services, models, and other components.

## Code Changes
### Models Enhancements (2024-03-21)
#### Game Model
- Added comprehensive game information tracking:
  - Website and store URLs
  - Price and currency support
  - Free-to-play and demo flags
  - Age rating and average playtime
- Added ESRBRatings class with predefined ratings (E, E10+, T, M, AO, RP)
- Added helper methods for price and age rating updates
- Enhanced validation for all fields
- Added new game statuses (Preordered, On Hold)
- Added IsValidStatus method for status validation

#### User Model
- Added user preference management:
  - Country and region fields
  - Premium subscription support
  - Theme preference
  - Notification preferences
  - User bio
- Added helper methods for:
  - Premium status management
  - Preference updates
  - Location updates
  - Notification settings
- Enhanced validation for all fields

#### UserCollection Model
- Added advanced collection features:
  - Playthrough status tracking
  - Completion percentage
  - Hidden flag
  - Custom status support
  - Tags support
- Added helper methods for:
  - Completion tracking
  - Tag management
  - Custom status management
  - Hidden state toggle
- Enhanced validation for all fields
- Improved status management with completion tracking

## Project Idea
- The project is a game catalog application built using .NET MAUI, allowing users to search and add games using the RAWG API. It includes features for authentication and local storage via SQLite.

## Code Breakdown

### Services
- **AuthenticationService**: Handles user authentication, including Google login and demo login functionality. This service manages user sessions and ensures secure access to the application.
- **RAWGService**: Manages interactions with the RAWG API for searching and retrieving game data. This service is responsible for fetching game information based on user queries.
- **SQLiteService**: Provides local storage functionality for games and user data using SQLite. This service allows the application to store and retrieve data locally, enhancing performance and offline capabilities.

### Models
- **Game**: Represents a game entity with properties such as GameId, Title, CoverArtUrl, and Description. This model is used to structure game data throughout the application.
- **User**: Represents a user entity with properties such as Id and Email. This model is used to manage user information and authentication.
- **UserCollection**: Represents a user's game collection with properties for tracking game status, ratings, and playtime.

### ViewModels
- **AddGameViewModel**: Manages the logic for adding games, including searching for games and handling user interactions. This ViewModel connects the UI with the underlying data and services.

### Views
- **MainPage**: The main user interface of the application, displaying a welcome message and a counter button. This view serves as the entry point for users.

### Other Components
- **App.xaml.cs**: Initializes the application and sets up the main window. This file is crucial for the application's startup process.
- **AppShell.xaml**: Defines the shell of the application, including navigation and layout. This component helps in structuring the application's UI and navigation flow.

## Auto-Update Mechanism
- The memory bank can be automatically updated using Git hooks. A pre-commit or post-commit hook can be set up to prompt or require updates to this file whenever changes are made to the codebase. This ensures that the memory bank remains current with the latest code changes and project developments. 
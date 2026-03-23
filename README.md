# Smart Campus: AI-Powered Digital Food Ordering System
## Overview
Smart Campus is a robust digital solution designed to eliminate long cafeteria queues and streamline the food ordering process for university students. By leveraging a Telegram-based interface and a powerful Django backend, the system allows students to browse menus, place orders, and make secure digital payments from the comfort of their dorm rooms.

Status: Core functionality complete. Currently transitioning into an AI-integrated ecosystem for predictive meal management.

## Features
- PostgreSQL Database integration.
- Secure environment configuration using `python-dotenv`.
- Media file management for menu items.
- Timezone configured for Africa/Addis_Ababa.

## The Problem & Our Solution
The Problem: University students often face 30-45 minute wait times at campus cafes, leading to wasted time and overcrowded dining halls.

The Solution: A seamless, real-time ordering bot that provides:

Pre-ordering: Order food before arriving at the cafe.

Secure Payments: Integrated with Chapa (Testing phase) for local bank transfers (CBE, Telebirr).

Instant Notification: Real-time updates for both students and cafe owners.

## Tech Stack
Backend: Python / Django (Robust & Scalable)

Interface: Telebot (Telegram API) for lightweight, low-data usage.

Database: PostgreSQL/SQLite (Relational data integrity).

Payment Integration: Chapa API (Webhooks for instant verification).

Security: OTP-based email verification, Hashed credentials, and Role-based access control.

## The AI Vision (Roadmap)
We are currently working on integrating Machine Learning models to transform the student experience:

Demand Forecasting: Using historical order data to predict "peak hours," helping cafe owners prepare ingredients in advance and reduce food waste.

Smart Recommendations: An NLP-driven engine that suggests meals based on student preferences and nutritional balance.

Dynamic Queue Management: An AI algorithm to provide real-time "Estimated Time of Readiness" based on current kitchen load.

## Project Structure (Key Modules)
bot.py: The central hub for user interaction, handling the state machine for orders and registration.

models.py: A sophisticated data architecture featuring specialized profiles for Students and Cafe Owners.

views.py: Secure Webhook handling for asynchronous payment confirmation.

## How to Run
Clone the repository.

Install dependencies: pip install -r requirements.txt.

Set up your .env (Telegram Token, Chapa Key, Email credentials).

Run migrations: python manage.py migrate.

Start the bot: python bot.py.

Developed by Amir Seid Empowering campus life through intelligent automation.

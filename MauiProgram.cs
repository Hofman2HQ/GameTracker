using Microsoft.Maui;
using Microsoft.Maui.Hosting;
using MyGameCatalog.Services;
using MyGameCatalog.Services.Interfaces;
using MyGameCatalog.ViewModels;
using MyGameCatalog.Views;
using Microsoft.Extensions.DependencyInjection;
using CommunityToolkit.Maui; // Optional – for additional toolkit features

namespace MyGameCatalog
{
    public static class MauiProgram
    {
        // IMPORTANT: Replace these values with your actual API keys/URLs.
        public const string RAWG_API_KEY = "8d36aa1c37c446b1927c78c5824886df";
        public const string FirebaseBaseUrl = "https://mygamecatalog-c99a2-default-rtdb.europe-west1.firebasedatabase.app/";

        public static MauiApp CreateMauiApp()
        {
            var builder = MauiApp.CreateBuilder();
            builder
                .UseMauiApp<App>()
                .UseMauiCommunityToolkit() // Optional
                .ConfigureFonts(fonts =>
                {
                    fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
                });

            // Register services for DI.
            builder.Services.AddSingleton<ISQLiteService, SQLiteService>();
            builder.Services.AddSingleton<IRAWGService>(s => new RAWGService(RAWG_API_KEY));
            builder.Services.AddSingleton<IAuthenticationService, AuthenticationService>();
            builder.Services.AddSingleton<IFirebaseService>(s => new FirebaseService(FirebaseBaseUrl));

            // Register view models.
            builder.Services.AddTransient<LoginViewModel>();
            builder.Services.AddTransient<MainViewModel>();
            builder.Services.AddTransient<AddGameViewModel>();

            // Register pages.
            builder.Services.AddTransient<LoginPage>();
            builder.Services.AddTransient<MainPage>();
            builder.Services.AddTransient<AddGamePage>();

            var app = builder.Build();

            // Initialize SQLite (synchronously for startup simplicity).
            var sqliteService = app.Services.GetService<ISQLiteService>();
            sqliteService.InitializeAsync().Wait();

            return app;
        }
    }
}
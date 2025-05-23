using Microsoft.Extensions.Logging;
using Microsoft.Maui.Controls.Hosting;
using Microsoft.Maui.Hosting;
using MyGameCatalog.Services;
using MyGameCatalog.Services.Interfaces;
using MyGameCatalog.ViewModels;
using MyGameCatalog.Views;
using CommunityToolkit.Maui; // Optional – for additional toolkit features

namespace MyGameCatalog
{
    public static class MauiProgram
    {
        public static MauiApp CreateMauiApp()
        {
            var builder = MauiApp.CreateBuilder();
            builder
                .UseMauiApp<App>()
                .UseMauiCommunityToolkit() // Optional
                .ConfigureFonts(fonts =>
                {
                    fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
                    fonts.AddFont("OpenSans-Semibold.ttf", "OpenSansSemibold");
                });

            // Register configuration first as other services might depend on it
            builder.Services.AddSingleton<IConfigurationService, ConfigurationService>();

            // Register core services
            builder.Services.AddSingleton<ISQLiteService, SQLiteService>();
            builder.Services.AddSingleton<IAuthenticationService, AuthenticationService>();

            // Register services with configuration
            builder.Services.AddSingleton<IRAWGService>(serviceProvider =>
            {
                var config = serviceProvider.GetRequiredService<IConfigurationService>();
                var apiKey = config.GetValue("RAWG_API_KEY") ?? "8d36aa1c37c446b1927c78c5824886df";
                return new RAWGService(apiKey);
            });

            builder.Services.AddSingleton<IFirebaseService>(serviceProvider =>
            {
                var config = serviceProvider.GetRequiredService<IConfigurationService>();
                var baseUrl = config.GetValue("FirebaseBaseUrl") ?? "https://mygamecatalog-c99a2-default-rtdb.europe-west1.firebasedatabase.app";
                return new FirebaseService(baseUrl);
            });

            // Register view models
            builder.Services.AddTransient<LoginViewModel>();
            builder.Services.AddTransient<MainViewModel>();
            builder.Services.AddTransient<AddGameViewModel>();

            // Register pages
            builder.Services.AddTransient<LoginPage>();
            builder.Services.AddTransient<MainPage>();
            builder.Services.AddTransient<AddGamePage>();

#if DEBUG
            builder.Logging.AddDebug();
#endif

            var app = builder.Build();

            // Initialize configuration
            var configService = app.Services.GetRequiredService<IConfigurationService>();
            configService.LoadAsync().GetAwaiter().GetResult();

            // Initialize database
            var dbService = app.Services.GetRequiredService<ISQLiteService>();
            dbService.InitializeAsync().GetAwaiter().GetResult();

            return app;
        }
    }
}
using System.Threading.Tasks;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.Services
{
    public class AuthenticationService : IAuthenticationService
    {
        public async Task<string> LoginWithGoogleAsync()
        {
            // TODO: Replace with a full OAuth integration (e.g., MSAL).
            await Task.Delay(1000); // Simulate asynchronous login.
            return "user@example.com"; // Dummy user email.
        }
    }
}
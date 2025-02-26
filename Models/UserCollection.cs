using SQLite;
using System;

namespace MyGameCatalog.Models
{
    public class UserCollection
    {
        [PrimaryKey, AutoIncrement]
        public int Id { get; set; }
        
        public int UserId { get; set; }
        public int GameId { get; set; }
        public string Status { get; set; }  // e.g., "Backlog", "In Progress", etc.
        public int? Rating { get; set; }
        public string Notes { get; set; }
        public DateTime DateAdded { get; set; }
    }
}
